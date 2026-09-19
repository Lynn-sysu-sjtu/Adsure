# -*- coding: utf-8 -*-
"""ASR 字级时间戳验收（实施方案 v2 §11：字级时间戳误差 ≤ 0.5s；§14 事项③）。

两件事分开做：

1) verify：对已留存的 ASR 产物做**结构性验收** —— 供应商是不是真给了
   字级时间戳（每段有 words、数值合法、单调、覆盖文本）。
   接新供应商/换账号后第一件事就跑它；不通过就换供应商，不要将就。

       python backend/scripts/verify_asr_word_timestamps.py verify \\
           data/video_mvp/jobs/<id>/asr_raw.json [更多文件...]

2) measure：拿人工标注的「词/短语 → 真实秒数」标签，量化时间误差。
   这是 §11 的硬指标（≤0.5s），标签必须人工核对，不许用 ASR 自己的输出自证。

       python backend/scripts/verify_asr_word_timestamps.py measure \\
           data/video_mvp/jobs/<id>/asr_raw.json \\
           --labels datasets/golden/asr_timestamp_labels/<name>.yaml

输入兼容旧 MVP 的 asr_raw.json：{"provider", "segments": [
    {"text", "start", "end", "words": [{"word","start","end"}]} ]}。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from app.pipeline.providers.volcengine import _strip_punct  # noqa: E402

WORD_COVERAGE_MIN = 0.9
SLOW_WORD_WARN_SECONDS = 2.0
ERROR_TOLERANCE_S = 0.5


@dataclass
class SegmentCheck:
    index: int
    ok: bool
    problems: list[str]
    warnings: list[str]


def _load_segments(path: Path) -> tuple[dict, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(segments, list):
        raise ValueError(f"{path}: 找不到 segments 数组")
    return payload, segments


def verify_file(path: Path) -> tuple[bool, list[str]]:
    """返回 (是否通过, 详情行)。失败必须明确，绝不静默放行。"""
    payload, segments = _load_segments(path)
    provider = payload.get("provider", "?")
    status = payload.get("status", "?")
    lines = [f"{path} | provider={provider} | status={status}"]

    # 无声/失败/无音轨的产物本来就不该有字级时间戳，跳过但明示
    if not segments and status in {"silent", "no_speech_detected", "no_audio_track",
                                   "failed", "partial"}:
        lines.append("  SKIP：无有效转写段落（状态 %s），无法据此验收字级能力" % status)
        return status != "failed", lines

    all_ok = True
    slow_words = 0
    for i, seg in enumerate(segments):
        chk = _check_segment(i, seg)
        if not chk.ok:
            all_ok = False
        for p in chk.problems:
            lines.append(f"  FAIL [{i}] {p}")
        for w in chk.warnings:
            lines.append(f"  warn [{i}] {w}")
        slow_words += len(chk.warnings)

    n = len(segments)
    if all_ok:
        lines.append(f"  PASS：{n} 段全部带字级时间戳"
                     + (f"；{slow_words} 个长跨度 token 需人工抽看" if slow_words else ""))
    return all_ok, lines


def _check_segment(i: int, seg: dict) -> SegmentCheck:
    problems, warnings = [], []
    text = seg.get("text") or ""
    words = seg.get("words")
    if not isinstance(words, list) or not words:
        return SegmentCheck(i, False,
                            ["该段没有 words 字段 —— 只是段级时间，不满足硬指标"], [])

    prev_end = None
    chars = 0
    for j, w in enumerate(words):
        token = w.get("word")
        try:
            ws, we = float(w["start"]), float(w["end"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"word[{j}]={token!r} 缺合法 start/end")
            continue
        if ws < 0 or we < ws:
            problems.append(f"word[{j}]={token!r} 时间非法 {ws:.2f}→{we:.2f}")
        if prev_end is not None and ws + 0.05 < prev_end:
            problems.append(f"word[{j}]={token!r} 时间回退 {ws:.2f} < {prev_end:.2f}")
        if we - ws > SLOW_WORD_WARN_SECONDS:
            warnings.append(f"word[{j}]={token!r} 跨度 {we-ws:.2f}s，疑似伪字级")
        prev_end = we
        chars += len(str(token or ""))

    coverage = chars / max(1, len(_strip_punct(text)))
    if coverage < WORD_COVERAGE_MIN:
        problems.append(f"words 对文本覆盖率 {coverage:.0%} < {WORD_COVERAGE_MIN:.0%}")
    if seg.get("end") and words:
        last_end = words[-1].get("end", 0)
        seg_end = float(seg["end"])
        try:
            if abs(float(last_end) - seg_end) > 1.0:
                warnings.append(
                    f"末字 {float(last_end):.2f}s 与段尾 {seg_end:.2f}s 相差 >1s")
        except (TypeError, ValueError):
            pass
    return SegmentCheck(i, not problems, problems, warnings)


# ── measure：人工标签误差 ─────────────────────────────────────


def measure_file(asr_path: Path, labels_path: Path,
                 tolerance: float) -> tuple[bool, list[str]]:
    _, segments = _load_segments(asr_path)
    labels = yaml.safe_load(labels_path.read_text(encoding="utf-8")) or {}
    cases = labels.get("cases") or []
    if not cases:
        raise ValueError(f"{labels_path}: 没有 cases")

    # 拼一条字级全局时间轴（标点不占位，与 provider 的 text 拼接口径一致）
    timeline: list[tuple[str, float, float]] = []
    for seg in segments:
        for w in seg.get("words") or []:
            timeline.append((str(w.get("word") or ""),
                             float(w["start"]), float(w["end"])))
    joined = "".join(t for t, _, _ in timeline)

    lines = [f"{asr_path.name} × {labels_path.name}｜容忍 {tolerance:.1f}s"]
    all_ok = True
    errors = []
    for n, case in enumerate(cases):
        phrase = str(case["phrase"])
        true_start = float(case["true_start"])
        pos = joined.find(_strip_punct(phrase))
        if pos < 0:
            all_ok = False
            lines.append(f"  FAIL [{n}] 转写中找不到短语 {phrase!r}（召回问题，非时间戳问题）")
            continue
        t0 = timeline[pos][1]
        t1 = timeline[pos + len(_strip_punct(phrase)) - 1][2]
        d_start = abs(t0 - true_start)
        d_end = abs(t1 - float(case.get("true_end", true_start)))
        errors.append(d_start)
        ok = d_start <= tolerance and d_end <= tolerance
        all_ok = all_ok and ok
        mark = "PASS" if ok else "FAIL"
        lines.append(
            f"  {mark} [{n}] {phrase!r} 标注 {true_start:.2f}s "
            f"实测 {t0:.2f}–{t1:.2f}s 起点误差 {d_start:.2f}s 终点误差 {d_end:.2f}s")

    if errors:
        lines.append(f"  起点误差 max={max(errors):.2f}s mean={sum(errors)/len(errors):.2f}s")
    return all_ok, lines


def main() -> int:
    ap = argparse.ArgumentParser(description="ASR 字级时间戳验收")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="结构验收留存的 ASR 产物")
    v.add_argument("files", nargs="+", type=Path)

    m = sub.add_parser("measure", help="对人工标签量化时间误差（硬指标 0.5s）")
    m.add_argument("asr_file", type=Path)
    m.add_argument("--labels", required=True, type=Path)
    m.add_argument("--tolerance", type=float, default=ERROR_TOLERANCE_S)

    args = ap.parse_args()
    ok_all = True

    if args.cmd == "verify":
        for f in args.files:
            ok, lines = verify_file(f)
            ok_all = ok_all and ok
            print("\n".join(lines))
    else:
        ok, lines = measure_file(args.asr_file, args.labels, args.tolerance)
        ok_all = ok
        print("\n".join(lines))

    print("\n结论：", "PASS ✅" if ok_all else "FAIL ❌（不达标，不得作为时间定位依据）")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
