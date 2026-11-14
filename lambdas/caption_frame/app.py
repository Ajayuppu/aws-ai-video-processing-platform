"""video-caption-frame: describe one key frame with Amazon Nova (Bedrock Converse API).

Called by the Step Functions Map state, once per frame. Input:
  {"jobId": "job-...", "bucket": "my-bucket", "key": "work/job-.../frames/frame_001.jpg"}
Output:
  {"key": "...", "caption": "A short description of the frame"}

Environment variables:
  MODEL_ID  Bedrock model or inference profile ID, default us.amazon.nova-2-lite-v1:0
"""
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-2-lite-v1:0")
s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")

PROMPT = ("Describe what is shown in this video frame in one or two sentences. "
          "Mention any visible text, objects or diagrams. Do not guess beyond what is visible.")


def handler(event, context):
    obj = s3.get_object(Bucket=event["bucket"], Key=event["key"])
    image_bytes = obj["Body"].read()

    response = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{
            "role": "user",
            "content": [
                {"image": {"format": "jpeg", "source": {"bytes": image_bytes}}},
                {"text": PROMPT},
            ],
        }],
        inferenceConfig={"maxTokens": 200, "temperature": 0.2},
    )

    blocks = response["output"]["message"]["content"]
    caption = " ".join(b["text"] for b in blocks if "text" in b).strip()
    logger.info("Captioned %s (%d tokens in, %d out)", event["key"],
                response["usage"]["inputTokens"], response["usage"]["outputTokens"])
    return {"key": event["key"], "caption": caption}
