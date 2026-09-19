#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv-video/bin/python -m src.video_mvp.asr --download-model medium
.venv-video/bin/python -m src.video_mvp.setup_models
