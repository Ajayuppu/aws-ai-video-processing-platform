"""Offline unit tests: no AWS account or network needed (boto3 clients are mocked).

Run:  python -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")


def load(name):
    spec = importlib.util.spec_from_file_location(f"lambda_{name}", ROOT / "lambdas" / name / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StartJobTests(unittest.TestCase):
    def setUp(self):
        os.environ["STATE_MACHINE_ARN"] = "arn:aws:states:us-east-1:111122223333:stateMachine:video-ai-pipeline"
        self.mod = load("start_job")
        self.mod.sfn = mock.MagicMock()
        self.mod.sfn.exceptions.ExecutionAlreadyExists = type("ExecutionAlreadyExists", (Exception,), {})

    def record(self, key, mid="m1"):
        body = {"id": "evt-1", "detail": {"bucket": {"name": "b"}, "object": {"key": key, "sequencer": "0055"}}}
        return {"messageId": mid, "body": json.dumps(body)}

    def test_starts_execution_with_deterministic_job_id(self):
        out = self.mod.handler({"Records": [self.record("uploads/clip.mp4")]}, None)
        self.assertEqual(out, {"batchItemFailures": []})
        kwargs = self.mod.sfn.start_execution.call_args.kwargs
        self.assertTrue(kwargs["name"].startswith("job-"))
        self.assertEqual(json.loads(kwargs["input"]),
                         {"jobId": kwargs["name"], "bucket": "b", "key": "uploads/clip.mp4"})
        again = self.mod.job_id_for("b", "uploads/clip.mp4", "0055", "evt-1")
        self.assertEqual(again, kwargs["name"])

    def test_skips_unsafe_keys(self):
        self.mod.handler({"Records": [self.record("uploads/my clip.mp4"), self.record("uploads/notes.txt")]}, None)
        self.mod.sfn.start_execution.assert_not_called()

    def test_duplicate_delivery_is_ignored(self):
        self.mod.sfn.start_execution.side_effect = self.mod.sfn.exceptions.ExecutionAlreadyExists()
        out = self.mod.handler({"Records": [self.record("uploads/clip.mp4")]}, None)
        self.assertEqual(out["batchItemFailures"], [])

    def test_reports_failed_messages(self):
        self.mod.sfn.start_execution.side_effect = RuntimeError("boom")
        out = self.mod.handler({"Records": [self.record("uploads/clip.mp4", mid="bad")]}, None)
        self.assertEqual(out["batchItemFailures"], [{"itemIdentifier": "bad"}])


class UpdateStatusTests(unittest.TestCase):
    def setUp(self):
        os.environ["APPSYNC_URL"] = "https://example.appsync-api.us-east-1.amazonaws.com/graphql"
        self.mod = load("update_status")
        self.mod.table = mock.MagicMock()
        self.mod.table.update_item.return_value = {"Attributes": {
            "jobId": "job-1", "status": "EXTRACTING", "progress": 15, "message": "m",
            "updatedAt": "2026-11-14T15:00:00.000Z"}}

    def test_builds_update_expression_with_optional_fields(self):
        item = self.mod.save_to_dynamodb({"jobId": "job-1", "status": "EXTRACTING", "progress": 15,
                                          "message": "m", "tags": ["a"]})
        kwargs = self.mod.table.update_item.call_args.kwargs
        self.assertEqual(kwargs["Key"], {"jobId": "job-1"})
        self.assertIn("#c = if_not_exists(#c, :u)", kwargs["UpdateExpression"])
        self.assertIn("message", kwargs["ExpressionAttributeNames"].values())
        self.assertIn("tags", kwargs["ExpressionAttributeNames"].values())
        self.assertNotIn("summary", kwargs["ExpressionAttributeNames"].values())
        self.assertEqual(item["status"], "EXTRACTING")

    def test_handler_survives_appsync_failure(self):
        with mock.patch.object(self.mod, "publish_to_appsync", side_effect=RuntimeError("down")):
            out = self.mod.handler({"jobId": "job-1", "status": "EXTRACTING", "progress": 15}, None)
        self.assertEqual(out["status"], "EXTRACTING")

    def test_publish_signs_request_with_sigv4(self):
        item = {"jobId": "job-1", "status": "COMPLETED", "progress": 100, "updatedAt": "2026-11-14T15:00:00.000Z"}
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = json.dumps(
            {"data": {"publishJobUpdate": {"jobId": "job-1"}}}).encode()
        with mock.patch.object(self.mod.urllib.request, "urlopen", return_value=fake) as urlopen:
            out = self.mod.publish_to_appsync(item)
        request = urlopen.call_args.args[0]
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertTrue(headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=test/"))
        self.assertIn("/us-east-1/appsync/aws4_request", headers["authorization"])
        self.assertEqual(out["jobId"], "job-1")
        sent = json.loads(request.data)
        self.assertEqual(sent["variables"]["input"]["status"], "COMPLETED")

    def test_missing_fields_raise(self):
        with self.assertRaises(ValueError):
            self.mod.handler({"jobId": "job-1"}, None)


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load("summarize")

    def test_parse_model_json_handles_code_fences(self):
        out = self.mod.parse_model_json('Here you go:\n```json\n{"title": "T", "summary": "S", "tags": ["A", " B "]}\n```')
        self.assertEqual(out, {"title": "T", "summary": "S", "tags": ["a", "b"]})

    def test_parse_model_json_accepts_comma_separated_tags(self):
        out = self.mod.parse_model_json('{"title": "T", "summary": "S", "tags": "x, y"}')
        self.assertEqual(out["tags"], ["x", "y"])

    def test_parse_model_json_rejects_prose(self):
        with self.assertRaises(ValueError):
            self.mod.parse_model_json("no json here")


if __name__ == "__main__":
    unittest.main()
