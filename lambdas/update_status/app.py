"""video-update-status: write job progress to DynamoDB, then push it to browsers through AWS AppSync.

Called by Step Functions at every stage. The payload looks like:
  {"jobId": "job-...", "status": "EXTRACTING", "progress": 15, "message": "...",
   "videoKey": "uploads/x.mp4", "title": "...", "summary": "...", "tags": ["a", "b"]}
Only jobId, status and progress are required.

Environment variables:
  TABLE_NAME     DynamoDB table (VideoJobs)
  APPSYNC_URL    GraphQL endpoint, https://<api-id>.appsync-api.us-east-1.amazonaws.com/graphql
"""
import datetime
import json
import logging
import os
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
table = boto3.resource("dynamodb").Table(os.environ.get("TABLE_NAME", "VideoJobs"))

MUTATION = """
mutation Publish($input: JobUpdateInput!) {
  publishJobUpdate(input: $input) {
    jobId status progress message videoKey title summary tags updatedAt
  }
}
"""

OPTIONAL_FIELDS = ["message", "videoKey", "title", "summary", "tags"]


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def save_to_dynamodb(payload):
    """UpdateItem creates the item on the first call and updates it afterwards."""
    names = {"#s": "status", "#p": "progress", "#u": "updatedAt", "#c": "createdAt"}
    values = {":s": payload["status"], ":p": int(payload["progress"]), ":u": now_iso()}
    sets = ["#s = :s", "#p = :p", "#u = :u", "#c = if_not_exists(#c, :u)"]

    for i, field in enumerate(OPTIONAL_FIELDS):
        if payload.get(field) is not None:
            names[f"#f{i}"] = field
            values[f":f{i}"] = payload[field]
            sets.append(f"#f{i} = :f{i}")

    resp = table.update_item(
        Key={"jobId": payload["jobId"]},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def publish_to_appsync(item):
    """Call the publishJobUpdate mutation signed with SigV4 (the Lambda role, not an API key)."""
    variables = {"input": {
        "jobId": item["jobId"],
        "status": item["status"],
        "progress": int(item["progress"]),
        "message": item.get("message"),
        "videoKey": item.get("videoKey"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "tags": item.get("tags"),
        "updatedAt": item["updatedAt"],
    }}
    body = json.dumps({"query": MUTATION, "variables": variables})
    url = os.environ["APPSYNC_URL"]

    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    aws_request = AWSRequest(method="POST", url=url, data=body,
                             headers={"Content-Type": "application/json"})
    SigV4Auth(credentials, "appsync", REGION).add_auth(aws_request)

    request = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers=dict(aws_request.headers.items()), method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.load(response)
    if result.get("errors"):
        raise RuntimeError(f"AppSync returned errors: {result['errors']}")
    return result["data"]["publishJobUpdate"]


def handler(event, context):
    for field in ("jobId", "status", "progress"):
        if field not in event:
            raise ValueError(f"Missing required field: {field}")

    item = save_to_dynamodb(event)
    try:
        publish_to_appsync(item)
    except Exception:
        # The status is already safe in DynamoDB; a failed live push must not fail the whole pipeline.
        logger.exception("Could not publish job %s to AppSync", item["jobId"])

    logger.info("Job %s -> %s (%s%%)", item["jobId"], item["status"], item["progress"])
    return {"jobId": item["jobId"], "status": item["status"], "progress": int(item["progress"])}
