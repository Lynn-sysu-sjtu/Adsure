# -*- coding: utf-8 -*-
"""把团队既有 video-mvp 的 job 重放进本项目链路。

用途：他们已经跑完的 job 不用重跑视频、不用再调一次 OCR，
直接把 evidence.json 导进来，就能获得本项目独有的能力：
字幕跨帧合并、违禁词粗筛（带法条与类案）、L4 必备要素与显著性核查。

跑法：
    python backend/scripts/replay_video_mvp.py [job目录或jobs根目录]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PipelineSettings
from app.pipeline.evidence import EvidenceSource
from app.pipeline.interop import load_job
from app.pipeline.merge import merge_ocr
from app.rules.mandatory import MandatoryChecker, MandatoryStatus
from app.rules.matcher import load_default_matcher

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_JOBS = ROOT / "data" / "video_mvp" / "jobs"


def replay(job_dir: Path, matcher, checker, cfg) -> dict:
    bundle = load_job(job_dir)
    job_meta = {}
    if (p := job_dir / "job.json").exists():
        job_meta = json.loads(p.read_text(encoding="utf-8"))
    their_report = {}
    if (p := job_dir / "report.json").exists():
        their_report = json.loads(p.read_text(encoding="utf-8"))

    industry_cn = job_meta.get("product_category") or job_meta.get("industry") or ""
    industry = {"游戏": "game", "保健食品": "health_food", "化妆品": "cosmetics"}.get(industry_cn)

    print("\n" + "=" * 78)
    print(f"  {job_meta.get('original_file_name') or job_dir.name}")
    print(f"  时长 {bundle.video.duration:.1f}s · 品类 {industry_cn or '未标注'} · "
          f"平台 {job_meta.get('platform') or '—'}")
    print("=" * 78)

    ocr_before = len(bundle.texts(EvidenceSource.OCR))
    asr_n = len(bundle.texts(EvidenceSource.ASR))
    bundle.evidences = merge_ocr(list(bundle.evidences), cfg)
    ocr_after = len(bundle.texts(EvidenceSource.OCR))

    print(f"\n① 字幕合并   逐帧 OCR {ocr_before} 条 → {ocr_after} 条花字"
          f"（压缩 {100 * (1 - ocr_after / max(ocr_before, 1)):.0f}%）"
          f"　口播证据 {asr_n} 条")

    hits = matcher.match_bundle(bundle, industry=industry)
    print(f"\n② 违禁词粗筛 命中 {len(hits)} 条")
    for h in hits[:8]:
        src = "口播" if h.source == EvidenceSource.ASR else "画面"
        print(f"     [{h.t_start:6.2f}s → {h.t_end:6.2f}s] {src} 「{h.matched_text}」"
              f"　{h.entry.law_ref}")
        print(f"        上下文：{h.context[:56]}")
    if len(hits) > 8:
        print(f"     …… 另有 {len(hits) - 8} 条")

    findings = checker.check_bundle(bundle, industry=industry)
    risky = [f for f in findings if f.counts_as_risk]
    advisory = [f for f in findings if f.is_risk and not f.counts_as_risk]
    print(f"\n③ 必备要素   核查 {len(findings)} 项 · 风险 {len(risky)} 项"
          f" · 仅提示 {len(advisory)} 项")
    for f in findings:
        mark = "●" if f.counts_as_risk else ("△" if f.is_risk else "○")
        tail = "（仅提示，不计入风险数）" if f.is_risk and not f.counts_as_risk else ""
        print(f"     {mark} {f.requirement.name} —— {f.status.label}{tail}")
        if f.status is MandatoryStatus.NOT_SALIENT:
            for m in f.failed_measures:
                print(f"          ✗ {m.name}：{m.measured}（要求 {m.threshold}）")

    theirs = (their_report.get("summary") or {}).get("risk_candidates")
    print(f"\n  对比：既有 MVP 报告 risk_candidates = {theirs}"
          f"　│　本次重放 违禁词 {len(hits)} + 必备要素风险 {len(risky)}"
          f"（另有仅提示 {len(advisory)} 项）")

    return {"job": job_dir.name, "hits": len(hits), "risky": len(risky),
            "advisory": len(advisory), "theirs": theirs}


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JOBS
    if not target.exists():
        sys.exit(f"找不到 {target}")

    jobs = ([target] if (target / "evidence.json").exists()
            else sorted(p for p in target.glob("*") if (p / "evidence.json").exists()))
    if not jobs:
        sys.exit(f"{target} 下没有可重放的 job")

    cfg = PipelineSettings()
    matcher = load_default_matcher()
    checker = MandatoryChecker()

    rows = [replay(j, matcher, checker, cfg) for j in jobs]

    print("\n" + "=" * 78)
    print("  汇总")
    print("=" * 78)
    print(f"  {'job':<12}{'既有MVP':>10}{'违禁词':>10}{'必备要素风险':>14}{'仅提示':>10}")
    for r in rows:
        print(f"  {r['job'][:10]:<12}{str(r['theirs']):>10}{r['hits']:>10}"
              f"{r['risky']:>14}{r['advisory']:>10}")
    print("\n  说明：本结果为风险自查提示，不构成侵权或违法认定。")
    print("       词库尚未经法务复核，命中需人工判断。\n")


if __name__ == "__main__":
    main()
