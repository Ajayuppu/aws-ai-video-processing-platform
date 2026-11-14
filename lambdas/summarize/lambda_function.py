"""video-summarize: turn the transcript and the frame captions into a title, a summary and tags.

Input from Step Functions:
  {"jobId": "job-...", "bucket": "my-bucket",
   "captions": [{"key": "...frame_001.jpg", "caption": "..."}, ...]}
Reads  s3://bucket/results/<jobId>/transcript.json   (written by Amazon Transcribe)
Writes s3://bucket/results/<jobId>/summary.json
Returns {"title": "...", "summary": "...", "tags": ["...", ...]}

Environment variables:
  MODEL_ID  Bedrock model or inference profile ID, default us.amazon.nova-2-lite-v1:0
"""
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-2-lite-v1:0")
MAX_TRANSCRIPT_CHARS = 12000      # keeps the prompt small and the cost predictable

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")

SYSTEM = [{"text": "You write concise, factual metadata for videos. Reply with JSON only."}]

INSTRUCTIONS = """Using the transcript and the frame descriptions below, return a JSON object with exactly these keys:
- "title": a descriptive title of at most 10 words
- "summary": a summary of 2 to 3 sentences
- "tags": an array of 5 to 8 lowercase tags (single words or short phrases)

Transcript:
{transcript}

Frame descriptions (in time order):
{captions}
"""


def read_transcript(bucket, job_id):
    obj = s3.get_object(Bucket=bucket, Key=f"results/{job_id}/transcript.json")
    data = json.loads(obj["Body"].read())
    transcripts = data.get("results", {}).get("transcripts", [])
    text = transcripts[0]["transcript"] if transcripts else ""
    return text[:MAX_TRANSCRIPT_CHARS] or "(no speech detected)"


def parse_model_json(text):
    """Models sometimes wrap JSON in prose or code fences. Take the outermost {...} block."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"No JSON object in model output: {text[:200]!r}")
    data = json.loads(text[start:end + 1])
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "title": str(data.get("title", "")).strip() or "Untitled video",
        "summary": str(data.get("summary", "")).strip(),
        "tags": [str(t).strip().lower() for t in tags][:8],
    }


def handler(event, context):
    bucket, job_id = event["bucket"], event["jobId"]
    transcript = read_transcript(bucket, job_id)
    captions = "\n".join(f"{i + 1}. {c['caption']}" for i, c in enumerate(event.get("captions", [])))

    response = bedrock.converse(
        modelId=MODEL_ID,
        system=SYSTEM,
        messages=[{"role": "user", "content": [{"text": INSTRUCTIONS.format(
            transcript=transcript, captions=captions or "(none)")}]}],
        inferenceConfig={"maxTokens": 600, "temperature": 0.2},
    )
    text = " ".join(b["text"] for b in response["output"]["message"]["content"] if "text" in b)
    result = parse_model_json(text)

    s3.put_object(Bucket=bucket, Key=f"results/{job_id}/summary.json",
                  Body=json.dumps(result, indent=2).encode("utf-8"), ContentType="application/json")
    logger.info("Summarized %s: %s", job_id, result["title"])
    return result
