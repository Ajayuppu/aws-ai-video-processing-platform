# Container image for the "extract media" step, run as an Amazon ECS task on AWS Fargate.
# It downloads one video from S3, extracts a mono FLAC audio track and a few JPEG key frames
# with FFmpeg, and uploads them back to S3.
FROM python:3.13-slim

# FFmpeg (includes ffprobe) from the Debian repositories. --no-install-recommends keeps the image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY process.py .

# Run as a non-root user.
RUN useradd --create-home appuser
USER appuser

# Everything the task needs comes from environment variables set by Step Functions
# (BUCKET, VIDEO_KEY, JOB_ID), so there is no CMD argument to pass.
ENTRYPOINT ["python", "/app/process.py"]
