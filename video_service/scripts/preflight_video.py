from __future__ import annotations
import importlib.util
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
errors=[]
def need(condition, message):
    if not condition: errors.append(message)

need(sys.version_info >= (3, 11), "需要 Python >= 3.11")
for command in ("ffmpeg", "ffprobe"):
    need(shutil.which(command) is not None, f"缺少系统命令：{command}")
for module in ("fastapi", "uvicorn", "httpx", "cv2", "rapidocr_onnxruntime", "faster_whisper", "sherpa_onnx"):
    need(importlib.util.find_spec(module) is not None, f"缺少 Python 依赖：{module}")
data=Path(os.getenv("VIDEO_SERVICE_DATA_DIR", str(ROOT/"data/video_service")))
data.mkdir(parents=True, exist_ok=True)
need(os.access(data, os.W_OK), f"数据目录不可写：{data}")
free=shutil.disk_usage(data).free
minimum=int(os.getenv("VIDEO_SERVICE_MIN_FREE_BYTES", str(2*1024**3)))
need(free>=minimum, f"磁盘剩余空间不足：{free} < {minimum}")
try:
    test=data/".preflight.sqlite3"
    with sqlite3.connect(test) as conn:
        conn.execute("create table if not exists t(id integer)")
    test.unlink(missing_ok=True)
except Exception as exc:
    errors.append(f"SQLite 不可用：{exc}")
need(bool(os.getenv("VIDEO_SERVICE_API_KEY")), "未配置 VIDEO_SERVICE_API_KEY")
warnings=[]
if not os.getenv("RULE_ENGINE_URL"):
    warnings.append("未配置 RULE_ENGINE_URL：任务只能产出证据（partial），不产出最终审核结果")
if errors:
    print("Video service preflight failed:")
    for item in errors: print("-", item)
    raise SystemExit(1)
for item in warnings: print(f"warning: {item}")
print(f"Video service preflight ok: data={data} free_bytes={free}")
