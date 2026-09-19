from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

errors: list[str] = []
warnings: list[str] = []


def need(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


# --- Python 与系统依赖 ---
need(sys.version_info >= (3, 11), "需要 Python >= 3.11")
for command in ("ffmpeg", "ffprobe"):
    need(shutil.which(command) is not None, f"缺少系统命令：{command}")

# av(PyAV) 是主抽取链路的容器解码依赖，缺失时只会在处理视频时才暴露，
# 因此必须在预检阶段拦住。
for module in (
    "fastapi",
    "uvicorn",
    "httpx",
    "av",
    "cv2",
    "rapidocr_onnxruntime",
    "faster_whisper",
    "sherpa_onnx",
):
    need(importlib.util.find_spec(module) is not None, f"缺少 Python 依赖：{module}")

# --- 数据目录与 SQLite ---
data = Path(os.getenv("VIDEO_SERVICE_DATA_DIR", str(ROOT / "data/video_service")))
data.mkdir(parents=True, exist_ok=True)
need(os.access(data, os.W_OK), f"数据目录不可写：{data}")
free = shutil.disk_usage(data).free
minimum = int(os.getenv("VIDEO_SERVICE_MIN_FREE_BYTES", str(2 * 1024**3)))
need(free >= minimum, f"磁盘剩余空间不足：{free} < {minimum}")
try:
    test = data / ".preflight.sqlite3"
    with sqlite3.connect(test) as conn:
        conn.execute("create table if not exists t(id integer)")
    test.unlink(missing_ok=True)
except Exception as exc:  # noqa: BLE001
    errors.append(f"SQLite 不可用：{exc}")

need(bool(os.getenv("VIDEO_SERVICE_API_KEY")), "未配置 VIDEO_SERVICE_API_KEY")

# --- 飞书审核响应契约 ---
schema_path = Path(
    os.getenv(
        "VIDEO_SERVICE_SCHEMA_PATH",
        str(ROOT / "data/schemas/audit_response_v0.2.schema.json"),
    )
)
need(schema_path.is_file(), f"缺少飞书审核响应 schema：{schema_path}")

# --- 平台规则来源完整性 ---
# manifest 记录原始文件 SHA256。证据文件必须逐字节保存，一旦被换行符转换
# （Windows autocrlf 等）就会校验失败，所以这里提前拦住。
manifest_path = Path(
    os.getenv(
        "VIDEO_SERVICE_PLATFORM_MANIFEST",
        str(ROOT / "data/platform_rules/manifest_2026-09-04.json"),
    )
)
if not manifest_path.is_file():
    warnings.append(f"未找到平台规则 manifest：{manifest_path}，跳过来源完整性校验")
else:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"平台规则 manifest 无法解析：{manifest_path}（{exc}）")
        manifest = {}
    for source in manifest.get("sources", []):
        raw_path = source.get("raw_path")
        expected = source.get("raw_sha256")
        if not raw_path or not expected:
            continue
        path = ROOT / raw_path
        if not path.is_file():
            errors.append(f"平台规则原始文件缺失：{raw_path}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(
                "平台规则原始文件 SHA256 不匹配："
                f"{raw_path}（expected={expected[:12]}…, actual={actual[:12]}…）"
            )

if not os.getenv("RULE_ENGINE_URL"):
    warnings.append("未配置 RULE_ENGINE_URL：任务只能产出证据（partial），不产出最终审核结果")

if errors:
    print("Video service preflight failed:")
    for item in errors:
        print("-", item)
    raise SystemExit(1)
for item in warnings:
    print(f"warning: {item}")
print(f"Video service preflight ok: data={data} free_bytes={free}")
