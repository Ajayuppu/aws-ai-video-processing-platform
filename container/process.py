#!/usr/bin/env python3
"""Extract audio and key frames from a video stored in S3.

Environment variables (set by AWS Step Functions through ECS container overrides):
  BUCKET      S3 bucket that holds the video and receives the outputs
  VIDEO_KEY   S3 key of the uploaded video, for example uploads/stereo-overview-60s.mp4
  JOB_ID      Unique job id; every output goes under work/<JOB_ID>/
  MAX_FRAMES  (optional) maximum number of key frames to extract, default 6

Outputs:
  s3://BUCKET/work/<JOB_ID>/audio.flac                 mono, 16 kHz, 16-bit FLAC
  s3://BUCKET/work/<JOB_ID>/frames/frame_001.jpg ...   evenly spaced JPEG key frames (max 1024 px wide)
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import boto3

MAX_FRAMES_DEFAULT = 6
# -nostdin: never wait for keyboard input; -y: overwrite outputs; quiet logs keep CloudWatch readable
FFMPEG = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "warning"]


def run(cmd):
    """Run a command, echo it to the logs, and raise if it fails."""
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def probe_duration(path):
    """Return the duration of the media file in seconds, using ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def extract_audio(video, out_dir):
    """Mono, 16 kHz FLAC: lossless and a format Amazon Transcribe accepts."""
    audio = out_dir / "audio.flac"
    run(FFMPEG + ["-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                  "-sample_fmt", "s16", "-c:a", "flac", str(audio)])
    return audio


def extract_frames(video, out_dir, duration, max_frames):
    """Take one frame every `interval` seconds, at most `max_frames` frames."""
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    interval = max(duration / max_frames, 1.0)
    # fps=1/interval -> one frame per interval; scale=1024:-2 -> 1024 px wide, even height
    run(FFMPEG + ["-i", str(video),
                  "-vf", f"fps=1/{interval:.3f},scale=1024:-2",
                  "-frames:v", str(max_frames), "-q:v", "3",
                  str(frames_dir / "frame_%03d.jpg")])
    return sorted(frames_dir.glob("frame_*.jpg"))


def main():
    bucket = os.environ["BUCKET"]
    video_key = os.environ["VIDEO_KEY"]
    job_id = os.environ["JOB_ID"]
    max_frames = int(os.environ.get("MAX_FRAMES", MAX_FRAMES_DEFAULT))

    s3 = boto3.client("s3")
    prefix = f"work/{job_id}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        video = tmp / "input_video"
        print(f"Downloading s3://{bucket}/{video_key}", flush=True)
        s3.download_file(bucket, video_key, str(video))

        duration = probe_duration(video)
        print(f"Duration: {duration:.1f} s", flush=True)

        audio = extract_audio(video, tmp)
        frames = extract_frames(video, tmp, duration, max_frames)
        if not frames:
            # Very short clip: grab the first frame so the next steps always have something to caption.
            frames_dir = tmp / "frames"
            frames_dir.mkdir(exist_ok=True)
            run(FFMPEG + ["-i", str(video), "-frames:v", "1",
                          "-vf", "scale=1024:-2", "-q:v", "3", str(frames_dir / "frame_001.jpg")])
            frames = sorted(frames_dir.glob("frame_*.jpg"))

        print(f"Uploading audio and {len(frames)} frame(s) to s3://{bucket}/{prefix}/", flush=True)
        s3.upload_file(str(audio), bucket, f"{prefix}/audio.flac")
        for frame in frames:
            s3.upload_file(str(frame), bucket, f"{prefix}/frames/{frame.name}",
                           ExtraArgs={"ContentType": "image/jpeg"})

    print("Done.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # a non-zero exit code makes the ECS task (and the Step Functions state) fail
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
