#!/usr/bin/env python3
"""Local smoke test for the video evidence service. Requires a running server."""
from __future__ import annotations
import os, sys
import httpx

base=os.getenv("VIDEO_SERVICE_URL","http://127.0.0.1:8520").rstrip("/")
key=os.getenv("VIDEO_SERVICE_API_KEY","change-me")
headers={"X-API-Key":key}

def fail(message): print("SMOKE_FAIL",message); sys.exit(1)
with httpx.Client(timeout=120) as client:
    ready_response=client.get(base+"/ready")
    if ready_response.status_code not in (200,503): fail(f"ready http={ready_response.status_code}")
    ready=ready_response.json()
    if not ready["jobs_db"]["ready"]: fail("jobs db not ready")
    print("ready_status",ready_response.status_code,
          "ffmpeg",ready["commands"]["ffmpeg"]["ready"],
          "rule_engine_url",ready["rule_engine"]["url_configured"])
    job_id=os.getenv("SMOKE_VIDEO_JOB_ID")
    if job_id:
        result=client.get(f"{base}/api/video/jobs/{job_id}/result",headers=headers).raise_for_status().json()
        print(result["status"]); sys.exit(0)
    # A tiny invalid file checks validation without requiring model files.
    bad=client.post(base+"/api/video/jobs",headers=headers,
                    files={"video":("bad.txt",b"not-video","text/plain")})
    if bad.status_code != 400: fail(f"invalid file status={bad.status_code}")
    print("smoke basic checks passed; upload a real MP4 for full extraction check")
