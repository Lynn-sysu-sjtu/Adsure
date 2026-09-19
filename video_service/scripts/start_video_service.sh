#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f deploy/video.env ]]; then set -a; . deploy/video.env; set +a; fi
HOST="${VIDEO_SERVICE_HOST:-127.0.0.1}"
PORT="${VIDEO_SERVICE_PORT:-8520}"
exec .venv-video/bin/python -m uvicorn src.video_service.service:app --host "$HOST" --port "$PORT" --workers 1
