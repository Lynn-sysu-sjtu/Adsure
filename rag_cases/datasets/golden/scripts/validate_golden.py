#!/usr/bin/env python3
"""机械校验金标准 YAML：结构、枚举、时间区间、bbox、双标完整性。

只查「机器能判定的形式错误」，不做法律对错判断。
分歧是否成立、标注是否准确，必须靠人工核对。

用法：
    python datasets/golden/scripts/validate_golden.py            # 校验 cases/
    python datasets/golden/scripts/validate_golden.py --all      # 含 examples/
退出码：0=无 error（可能有 warning）；1=存在 error。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
CASES_DIR = ROOT / "datasets" / "golden" / "cases"
EXAMPLES_DIR = ROOT / "datasets" / "golden" / "examples"
L4_YAML = ROOT / "backend" / "app" / "rules" / "lexicon" / "L4_mandatory.yaml"

CHANNELS = {"asr", "ocr", "visual"}
LAYERS = {"L1", "L2", "L3", "L4"}
EXPECTED = {"violation", "needs_facts", "not_applicable"}
STATUSES = {"draft", "dual_annotated", "adjudicated"}
IP_KINDS = {"character", "logo", "celebrity", "artwork", "font"}
INDUSTRIES = {"health_food", "cosmetics", "game", "general"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, case_id: str, msg: str) -> None:
        self.errors.append(f"[ERROR] {case_id}: {msg}")

    def warn(self, case_id: str, msg: str) -> None:
        self.warnings.append(f"[WARN ] {case_id}: {msg}")


def _known_l4_ids() -> set[str]:
    if not L4_YAML.exists():
        return set()
    data = yaml.safe_load(L4_YAML.read_text(encoding="utf-8")) or {}
    return {r.get("id") for r in (data.get("requirements") or []) if r.get("id")}


def _check_bbox(rep: Report, cid: str, where: str, bbox) -> bool:
    if bbox is None:
        return True
    if not (isinstance(bbox, list) and len(bbox) == 4):
        rep.err(cid, f"{where} bbox 必须是 4 个数 [x,y,w,h]")
        return False
    x, y, w, h = bbox
    ok = all(isinstance(v, (int, float)) for v in bbox)
    if ok and not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1
                   and x + w <= 1 + 1e-6 and y + h <= 1 + 1e-6):
        rep.err(cid, f"{where} bbox 越界：{bbox}")
        ok = False
    return ok


def validate_case(path: Path, rep: Report, l4_ids: set[str]) -> None:
    cid = path.stem
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        rep.err(cid, f"YAML 解析失败：{e}")
        return
    if not isinstance(data, dict):
        rep.err(cid, "顶层必须是映射")
        return

    if data.get("case_id") != cid:
        rep.err(cid, f"case_id={data.get('case_id')!r} 与文件名 {cid} 不一致")

    video = data.get("video") or {}
    duration = video.get("duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        rep.err(cid, "video.duration_seconds 必须为正数")
        duration = None
    sha = video.get("sha256")
    if not (isinstance(sha, str) and len(sha) == 64):
        rep.err(cid, "video.sha256 必须为 64 位十六进制")
    vpath = video.get("path")
    if not isinstance(vpath, str) or not vpath:
        rep.err(cid, "video.path 缺失")
    else:
        abs_v = (ROOT / vpath).resolve() if not Path(vpath).is_absolute() else Path(vpath)
        if abs_v.exists():
            h = hashlib.sha256(abs_v.read_bytes()).hexdigest() if abs_v.stat().st_size < 50_000_000 else None
            if h and h != sha:
                rep.err(cid, f"视频 sha256 与文件不符（文件 {h[:12]}…）")
        else:
            rep.warn(cid, f"视频文件当前不在仓库（{vpath}），分发后请以 sha256 核身")

    if data.get("industry") not in INDUSTRIES:
        rep.err(cid, f"industry 非法：{data.get('industry')!r}")
    if not data.get("platform"):
        rep.err(cid, "platform 缺失")

    def _check_span(item, where: str, need_bbox: bool) -> None:
        t0, t1 = item.get("t_start"), item.get("t_end")
        if not all(isinstance(v, (int, float)) for v in (t0, t1)):
            rep.err(cid, f"{where} 时间戳缺失或非数值")
            return
        if t0 < 0 or t1 <= t0:
            rep.err(cid, f"{where} 时间区间非法：{t0}→{t1}")
        if duration is not None and t1 > duration + 0.05:
            rep.err(cid, f"{where} t_end={t1} 超出视频时长 {duration}")
        if need_bbox:
            _check_bbox(rep, cid, where, item.get("bbox"))

    seen_ids: set[str] = set()
    for i, a in enumerate(data.get("annotations") or []):
        where = f"annotations[{i}] id={a.get('id', '?')}"
        if a.get("id") in seen_ids:
            rep.err(cid, f"{where} id 重复")
        seen_ids.add(a.get("id"))
        ch = a.get("channel")
        if ch not in CHANNELS:
            rep.err(cid, f"{where} channel 非法：{ch!r}")
        if a.get("layer") not in LAYERS:
            rep.err(cid, f"{where} layer 非法：{a.get('layer')!r}")
        if a.get("expected") not in EXPECTED:
            rep.err(cid, f"{where} expected 非法：{a.get('expected')!r}")
        _check_span(a, where, need_bbox=(ch == "ocr"))
        if ch == "ocr" and "bbox" not in a:
            rep.err(cid, f"{where} OCR 标注必须带 bbox")
        if ch == "asr" and a.get("bbox") is not None:
            rep.warn(cid, f"{where} ASR 标注不应带 bbox")
        if not a.get("text"):
            rep.err(cid, f"{where} text 缺失")

    for i, m in enumerate(data.get("mandatory_checks") or []):
        where = f"mandatory_checks[{i}] id={m.get('id', '?')}"
        rid = m.get("requirement_id")
        if l4_ids and rid not in l4_ids:
            rep.err(cid, f"{where} requirement_id={rid!r} 不在 L4 词库")
        if m.get("expected") not in EXPECTED:
            rep.err(cid, f"{where} expected 非法")
        if m.get("present") is True:
            spans = m.get("spans")
            if not spans:
                rep.err(cid, f"{where} present=true 必须给 spans")
            for j, sp in enumerate(spans or []):
                _check_span(sp, f"{where}.spans[{j}]", need_bbox=True)
        elif m.get("present") is not False:
            rep.err(cid, f"{where} present 必须为布尔值")

    for i, ip in enumerate(data.get("ip_ground_truth") or []):
        where = f"ip_ground_truth[{i}] id={ip.get('id', '?')}"
        if ip.get("kind") not in IP_KINDS:
            rep.err(cid, f"{where} kind 非法：{ip.get('kind')!r}")
        _check_span(ip, where, need_bbox=True)
        if ip.get("is_protected_ip") and not ip.get("ip_id"):
            rep.err(cid, f"{where} is_protected_ip=true 必须给 ip_id")
        if not isinstance(ip.get("is_protected_ip"), bool):
            rep.err(cid, f"{where} is_protected_ip 必须为布尔值")

    label = data.get("label") or {}
    status = label.get("status")
    if status not in STATUSES:
        rep.err(cid, f"label.status 非法：{status!r}")
    a_name = (label.get("annotator_a") or {}).get("name")
    b_name = (label.get("annotator_b") or {}).get("name")
    if status in {"dual_annotated", "adjudicated"}:
        if not a_name or not b_name:
            rep.err(cid, f"status={status} 必须有 annotator_a/b 两人")
        elif a_name == b_name:
            rep.err(cid, "双标不能是同一人")
    if status == "adjudicated" and not label.get("resolved_by"):
        rep.err(cid, "adjudicated 必须有 resolved_by")
    for d in label.get("disagreements") or []:
        if not d.get("a") or not d.get("b") or "reason_a" not in d or "reason_b" not in d:
            rep.err(cid, "disagreements 条目必须保留 a/b 双方答案与理由")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="同时校验 examples/")
    args = ap.parse_args()

    files = sorted(CASES_DIR.glob("*.yaml"))
    if args.all:
        files += sorted(EXAMPLES_DIR.glob("*.yaml"))
    if not files:
        print("没有找到案例文件（cases/*.yaml）")
        return 0

    rep = Report()
    l4_ids = _known_l4_ids()
    for f in files:
        validate_case(f, rep, l4_ids)

    for line in rep.errors + rep.warnings:
        print(line)
    print(f"\n校验 {len(files)} 个文件：{len(rep.errors)} error, {len(rep.warnings)} warning")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
