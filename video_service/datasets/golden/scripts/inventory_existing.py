#!/usr/bin/env python3
"""清点仓库里现成的视频素材，产出金标准候选清单。

纯标准库实现：时长直接解析 MP4 mvhd box，不依赖 ffprobe（本机可能没装）。

用法：
    python datasets/golden/scripts/inventory_existing.py
输出：
    datasets/golden/inventory/candidate_inventory.csv

注意：这只是**初筛**。data/video_mvp/jobs 下的是工程跑批素材，
是否能进金标准必须人工判断（真实性、代表性、是否含 IP、能否取得使用许可）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "datasets" / "golden" / "inventory" / "candidate_inventory.csv"

ROOT_TEST_VIDEOS = [
    "测试广告视频1.mp4",
    "测试广告视频2.mp4",
    "美妆广告测试视频.MP4",
]
JOBS_DIR = ROOT / "data" / "video_mvp" / "jobs"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def mp4_duration_seconds(path: Path) -> float | None:
    """解析 moov/mvhd 取时长。读不到就返回 None，不猜。"""
    try:
        with path.open("rb") as f:
            size = _file_size(f)
            moov = _find_box(f, b"moov", start=0, end=size)
            if moov is None:
                return None
            mvhd = _find_box(f, b"mvhd", start=moov[0], end=moov[1])
            if mvhd is None:
                return None
            f.seek(mvhd[0])
            version = f.read(1)[0]
            f.read(3)  # flags
            if version == 1:
                f.read(8 + 8)
                timescale = struct.unpack(">I", f.read(4))[0]
                duration = struct.unpack(">Q", f.read(8))[0]
            else:
                f.read(4 + 4)
                timescale = struct.unpack(">I", f.read(4))[0]
                duration = struct.unpack(">I", f.read(4))[0]
            return round(duration / timescale, 1) if timescale else None
    except (OSError, struct.error, IndexError):
        return None


def _file_size(f) -> int:
    pos = f.tell()
    f.seek(0, 2)
    size = f.tell()
    f.seek(pos)
    return size


def _find_box(f, wanted: bytes, start: int, end: int) -> tuple[int, int] | None:
    """在 [start, end) 内顺序扫描 box，返回 (payload_start, payload_end)。"""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        header = f.read(8)
        if len(header) < 8:
            return None
        size, box_type = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:  # 64 位 largesize
            size = struct.unpack(">Q", f.read(8))[0]
            header_size = 16
        if size < header_size:
            return None
        if box_type == wanted:
            return pos + header_size, pos + size
        pos += size
    return None


@dataclass
class Candidate:
    path: str
    role: str
    sha256: str
    size_mb: float
    duration_s: float | None
    evidence_items: int | None
    note: str


def _job_item_count(video: Path) -> int | None:
    ev = video.parent / "evidence.json"
    if not ev.exists():
        return None
    try:
        return len(json.loads(ev.read_text(encoding="utf-8")).get("items", []))
    except (json.JSONDecodeError, OSError):
        return None


def collect() -> list[Candidate]:
    out: list[Candidate] = []

    for rel in ROOT_TEST_VIDEOS:
        p = ROOT / rel
        if not p.exists():
            continue
        digest = sha256_of(p)
        out.append(Candidate(
            path=rel, role="root_test_video", sha256=digest,
            size_mb=round(p.stat().st_size / 1e6, 1),
            duration_s=mp4_duration_seconds(p), evidence_items=None,
            note="根目录历史测试视频；来源与授权需人工确认",
        ))

    if JOBS_DIR.exists():
        for job in sorted(JOBS_DIR.iterdir()):
            video = job / "source.mp4"
            if not video.exists():
                continue
            digest = sha256_of(video)
            out.append(Candidate(
                path=str(video.relative_to(ROOT)), role="engineering_job",
                sha256=digest, size_mb=round(video.stat().st_size / 1e6, 1),
                duration_s=mp4_duration_seconds(video),
                evidence_items=_job_item_count(video),
                note="工程跑批素材；evidence.json 可辅助预标注但不能代替人工金标准",
            ))

    # 标记重复文件
    seen: dict[str, str] = {}
    for c in out:
        if c.sha256 in seen:
            c.note += f"；与 {seen[c.sha256]} 内容重复"
        else:
            seen[c.sha256] = c.path
    return out


def main() -> None:
    rows = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["path", "role", "sha256", "size_mb", "duration_s",
                    "evidence_items", "note"])
        for c in rows:
            w.writerow([c.path, c.role, c.sha256, c.size_mb, c.duration_s,
                        c.evidence_items if c.evidence_items is not None else "",
                        c.note])

    uniq = {c.sha256 for c in rows}
    roles = {}
    for c in rows:
        roles[c.role] = roles.get(c.role, 0) + 1
    print(f"候选 {len(rows)} 条（去重后 {len(uniq)} 条）→ {OUT.relative_to(ROOT)}")
    for role, n in sorted(roles.items()):
        print(f"  {role}: {n}")


if __name__ == "__main__":
    main()
