"""video-start-job: SQS -> Step Functions.

EventBridge puts one S3 "Object Created" event into the SQS queue for every uploaded video.
This function reads a batch of those messages and starts one Step Functions execution per video.

Environment variables:
  STATE_MACHINE_ARN  ARN of the video-ai-pipeline state machine
"""
import hashlib
import json
import logging
import os
import re

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn = boto3.client("stepfunctions")

# Keep keys simple on purpose. Names with spaces or special characters are skipped instead of guessed at.
SAFE_KEY = re.compile(r"^uploads/[A-Za-z0-9._/-]+\.(mp4|mov|m4v|webm|mkv)$", re.IGNORECASE)


def job_id_for(bucket, key, sequencer, event_id):
    """Deterministic id: the same S3 event always maps to the same job (idempotent retries)."""
    basis = f"{bucket}/{key}/{sequencer or event_id}"
    return "job-" + hashlib.sha256(basis.encode()).hexdigest()[:16]


def handler(event, context):
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]
    failures = []

    for record in event["Records"]:
        try:
            body = json.loads(record["body"])          # the EventBridge event
            detail = body["detail"]
            bucket = detail["bucket"]["name"]
            key = detail["object"]["key"]
            sequencer = detail["object"].get("sequencer")

            if not SAFE_KEY.match(key):
                logger.warning("Skipping %s: not an uploads/*.mp4|mov|m4v|webm|mkv key with a simple name", key)
                continue

            job_id = job_id_for(bucket, key, sequencer, body.get("id"))
            try:
                sfn.start_execution(
                    stateMachineArn=state_machine_arn,
                    name=job_id,                       # execution names are unique for 90 days
                    input=json.dumps({"jobId": job_id, "bucket": bucket, "key": key}),
                )
                logger.info("Started execution %s for s3://%s/%s", job_id, bucket, key)
            except sfn.exceptions.ExecutionAlreadyExists:
                logger.info("Execution %s already exists (duplicate delivery), ignoring", job_id)
        except Exception:
            logger.exception("Failed to process message %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})

    # Partial batch response: only the failed messages go back to the queue (needs ReportBatchItemFailures).
    return {"batchItemFailures": failures}
