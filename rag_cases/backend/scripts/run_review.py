# -*- coding: utf-8 -*-
"""真实评审入口：跑完整链路并导出可供前端消费的报告 JSON。

与 `demo_pipeline.py` 的区别只有一个，但很关键：
**这里默认接真实大模型**（.env 里配了 key 就用），而不是脚本化替身。
替身的要件答案是预设的，看着漂亮但没有判断力；接了真模型，
④ 涵摄推理那一步才第一次具备实际的法律判断能力。

    # 用内置演示素材 + 真模型（.env 已配 LEX_DEEPSEEK_API_KEY）
    python backend/scripts/run_review.py --out out/report.json

    # 用当前 video_mvp 的真实 job 数据
    python backend/scripts/run_review.py --job data/video_mvp/jobs/<job_id> --out out/report.json

    # 不花钱、不联网，跑替身
    python backend/scripts/run_review.py --llm mock

导出的 JSON 同时带两套字段：
  · `报告` —— 给人看的六段式原文，与 PDF/飞书报告同源
  · 顶层数值字段（t_start/bbox/duration）—— 给前端画时间轴和证据框用
前端页面在 `frontend/review.html`，直接读这份 JSON。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))   # backend/  → app.*
sys.path.insert(0, str(_HERE))          # scripts/  → 复用 demo_pipeline 的素材

from app.config import PipelineSettings, get_settings
from app.pipeline.evidence import EvidenceSource
from app.pipeline.merge import merge_ocr
from app.reasoning.report import (
    DISCLAIMER, Report, finding_from_hit, finding_from_mandatory,
)
from app.reasoning.subsume import MockLLMProvider, Subsumer, get_llm_provider
from app.rules.mandatory import MandatoryChecker
from app.rules.matcher import load_default_matcher


def _bundle_from_demo():
    """复用演示素材，避免两处各写一份假数据导致口径漂移。"""
    from demo_pipeline import build_bundle
    return build_bundle()


def _bundle_from_job(job_dir: Path):
    from app.pipeline.interop import load_job
    return load_job(job_dir)


def _evidence_json(bundle) -> list[dict]:
    """证据流导出。前端画证据框要的是数值，不是格式化字符串。"""
    out = []
    for e in bundle.evidences:
        item = {
            "id": getattr(e, "id", ""),
            "source": getattr(getattr(e, "source", None), "value", str(getattr(e, "source", ""))),
            "text": getattr(e, "text", ""),
            "t_start": round(float(getattr(e, "t_start", 0.0)), 3),
            "t_end": round(float(getattr(e, "t_end", 0.0)), 3),
            "confidence": getattr(e, "confidence", None),
            "frame_ids": list(getattr(e, "frame_ids", []) or []),
        }
        bbox = getattr(e, "bbox", None)
        if bbox is not None:
            item["bbox"] = {"x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h}
        fs = getattr(e, "font_scale", None)
        if fs is not None:
            item["font_scale"] = fs
        out.append(item)
    return out


def _findings_json(report: Report) -> list[dict]:
    """每条风险 = 给人看的六段 + 给机器用的定位字段。"""
    out = []
    for f in report.findings:
        item = {
            "title": f.title,
            "t_start": round(f.t_start, 3),
            "t_end": round(f.t_end, 3),
            "source": f.source,
            "level": f.level.value,
            "level_label": f.level.label,
            "counts_as_risk": f.counts_as_risk,
            "category": f.category,
            "legal_basis": f.legal_basis,
            "报告": f.to_dict(),
        }
        if f.bbox:
            item["bbox"] = f.bbox
        if f.required_materials:
            item["required_materials"] = list(f.required_materials)
        if f.element_trace:
            item["element_trace"] = f.element_trace
        if f.similar_cases:
            item["similar_cases"] = f.similar_cases
        out.append(item)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="审心 Adsure · 视频合规评审")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--job", type=Path, help="video_mvp 格式的 job 目录")
    src.add_argument("--demo", action="store_true", help="用内置演示素材（默认）")
    ap.add_argument("--industry", default="health_food", help="行业赛道，决定 L2/L4 适用范围")
    ap.add_argument("--llm", choices=["auto", "mock", "deepseek"], default="auto",
                    help="auto=配了 key 就用真模型，否则替身")
    ap.add_argument("--background", default="产品已取得保健食品注册证书，功能为增强免疫力。",
                    help="送审背景事实，涵摄时作为已知事实提供给模型")
    ap.add_argument("--out", type=Path, help="报告 JSON 导出路径")
    args = ap.parse_args()

    cfg = PipelineSettings()
    settings = get_settings()

    # ── 选模型。这一步的诚实性比功能更重要：──────────────────────
    # 用了替身却不说，报告读起来和真推理一模一样，是在拿假结论骗自己。
    if args.llm == "mock":
        llm, llm_mode = MockLLMProvider(), "mock"
    elif args.llm == "deepseek":
        llm, llm_mode = get_llm_provider("deepseek"), "deepseek"
    else:
        if settings.llm_configured:
            llm, llm_mode = get_llm_provider(), settings.llm_provider
        else:
            llm, llm_mode = MockLLMProvider(), "mock"

    bundle = _bundle_from_job(args.job) if args.job else _bundle_from_demo()

    # ── 取证后处理 ────────────────────────────────────────────
    bundle.evidences = merge_ocr(list(bundle.evidences), cfg)

    # ── 找法 ──────────────────────────────────────────────────
    matcher = load_default_matcher()
    hits = matcher.match_bundle(bundle, industry=args.industry)
    mandatory = MandatoryChecker().check_bundle(bundle, industry=args.industry)

    # ── 用法 ──────────────────────────────────────────────────
    subsumer = Subsumer(llm=llm)
    report = Report(review_id=bundle.review_id, video_path=bundle.video.path,
                    duration=bundle.video.duration)

    print(f"涵摄推理：{len(hits)} 条命中，模型 = {llm_mode}"
          + ("（替身，要件答案非推理产物）" if llm_mode == "mock" else ""))
    for i, h in enumerate(hits, 1):
        sub, cases = subsumer.subsume_hit(
            h, background=args.background, industry=args.industry)
        report.findings.append(finding_from_hit(h, sub, cases))
        print(f"  [{i}/{len(hits)}] {h.matched_text} → {sub.verdict.value}")
    for f in mandatory:
        report.findings.append(finding_from_mandatory(f))

    # ── 汇总 ──────────────────────────────────────────────────
    print(f"\n整体风险等级：{report.level.label}"
          f"　│　风险 {len(report.risks)} 条　│　仅提示 {len(report.advisories)} 条")
    usage = getattr(llm, "usage_summary", lambda: "")()
    if usage:
        print(usage)

    if args.out:
        payload = {
            "meta": {
                "review_id": report.review_id,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "industry": args.industry,
                "video": {
                    "path": bundle.video.path,
                    "duration": bundle.video.duration,
                    "width": bundle.video.width,
                    "height": bundle.video.height,
                },
                "llm": {
                    "mode": llm_mode,
                    "is_real": llm_mode != "mock",
                    "usage": usage,
                },
                # 这两条必须随报告走，否则下游会把内部验证产物当成对外结论
                "lexicon_reviewed_by_legal": bool(
                    getattr(getattr(matcher, "lexicon", None), "reviewed_by_legal", False)),
                "data_source": "video_mvp job" if args.job else "内置演示素材（合成数据）",
            },
            "summary": {
                "level": report.level.value,
                "level_label": report.level.label,
                "risk_count": len(report.risks),
                "advisory_count": len(report.advisories),
            },
            "cost": {
                "frames_sampled": bundle.cost.frames_sampled,
                "frames_after_dedup": bundle.cost.frames_after_dedup,
                "dedup_ratio": round(bundle.cost.dedup_ratio, 4),
                "ocr_calls": bundle.cost.ocr_calls,
                "asr_calls": bundle.cost.asr_calls,
            },
            "evidence": _evidence_json(bundle),
            "findings": _findings_json(report),
            "disclaimer": DISCLAIMER,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n报告已导出：{args.out}")


if __name__ == "__main__":
    main()
