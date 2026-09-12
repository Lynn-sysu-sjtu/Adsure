#!/bin/zsh
set -eu
cd "${0:A:h:h}"
if [[ ! -x .venv-video/bin/python ]]; then
  print -u2 '请先用 Python 3.12 创建 .venv-video，并安装 requirements-video.txt，详见 docs/视频MVP-v2验收与使用.md。'
  exit 1
fi
exec .venv-video/bin/python -m uvicorn src.video_mvp.api:app \
  --host 127.0.0.1 --port "${VIDEO_MVP_PORT:-8510}"
