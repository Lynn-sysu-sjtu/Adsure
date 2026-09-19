# -*- coding: utf-8 -*-
"""IP 库加载器与起始清单（需与法务共同确认，见实施方案 v2 §5、§14 事项②）。

⚠️ 这是讨论底稿，不是权威清单：所有条目 reviewed_by_legal=false。
   参考图目录在 library/images/<ip_id>/ 下（包外收集、包内不发原图）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.ip.schema import IPLibrary, IPLibraryEntry

logger = logging.getLogger(__name__)

LIBRARY_ROOT = Path(__file__).resolve().parent / "library"
DEFAULT_YAML = LIBRARY_ROOT / "ip_library.seed.yaml"
IMAGE_ROOT = LIBRARY_ROOT / "images"

# 著作权与商标法两条路径都给：动漫形象走著作权（复制权/信息网络传播权等，
# 具体由涵摄层选条），logo 类走商标权。材料清单按方案示例统一给三项。
_GENERIC_MATERIALS = [
    "权利人或其授权主体出具的官方授权书",
    "授权范围与期限证明",
    "授权地域证明（覆盖本次投放地域）",
]
_GENERIC_LAW = ["《中华人民共和国著作权法》第十条", "《中华人民共和国商标法》第五十七条"]


def load_library(yaml_path: Path | str = DEFAULT_YAML) -> IPLibrary:
    """加载并校验 IP 库 YAML；缺图只警告不失败（法务清单先于参考图收集）。"""
    path = Path(yaml_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"IP 库格式错误：{path}")

    entries: list[IPLibraryEntry] = []
    seen: set[str] = set()
    for raw_entry in raw.get("entries", []):
        try:
            entry = IPLibraryEntry(**raw_entry)
        except ValidationError as e:
            raise ValueError(f"IP 库条目校验失败 at {path}: {raw_entry.get('ip_id')!r}\n{e}") from e
        if entry.ip_id in seen:
            raise ValueError(f"IP 库出现重复 ip_id: {entry.ip_id}")
        seen.add(entry.ip_id)
        if not entry.reference_images:
            logger.info("IP 条目 %s 暂无参考图，底库检索对该条目不生效（待收集）", entry.ip_id)
        else:
            missing = [
                rel for rel in entry.reference_images
                if not (IMAGE_ROOT / rel).exists()
            ]
            if missing:
                logger.info(
                    "IP 条目 %s 有 %d 张参考图缺失（先记台账，收集后补图即可）",
                    entry.ip_id, len(missing),
                )
        entries.append(entry)

    return IPLibrary(meta=raw.get("meta", {}), entries=entries)


def load_default_library() -> IPLibrary:
    return load_library(DEFAULT_YAML)

