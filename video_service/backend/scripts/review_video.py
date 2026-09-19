# -*- coding: utf-8 -*-
"""从一个真实 .mp4 开始，跑完整条链路。

这是与 `run_review.py` 的关键区别：那个脚本的入口是**已经识别好的证据流**，
本脚本的入口是**视频文件本身** —— 抽帧、分镜、去重、OCR、ASR 全都真跑。

    python backend/scripts/review_video.py data/video_mvp/jobs/<id>/source.mp4 \
        --out out/real_report.json

默认走本地开源模型（faster-whisper + RapidOCR），**不需要任何云账号**。
模型首次运行会自动下载并缓存。

⚠️ ASR 档位：默认 `small`。`base` 档中文识别质量差到不可用于对外报告，
   只适合验证机制。用 `--asr-model` 切换，或设环境变量 LOCAL_ASR_MODEL。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

from app.config import get_settings
from app.pipeline.evidence import CostRecord, EvidenceBundle, EvidenceSource
from app.pipeline.extract import extract
from app.pipeline.merge import merge_ocr
from app.pipeline.providers.base import CostLimitExceeded, ocr_budget_for
from app.pipeline.providers.local import LocalRapidOCR, LocalWhisperASR
from app.reasoning.report import DISCLAIMER, Report, finding_from_hit, finding_from_mandatory
from app.reasoning.subsume import MockLLMProvider, Subsumer, get_llm_provider
from app.rules.mandatory import MandatoryChecker
from app.rules.matcher import load_default_matcher
from run_review import _evidence_json, _findings_json


def main() -> None:
    ap = argparse.ArgumentParser(description="真实视频合规评审（本地模型，无需云账号）")
    ap.add_argument("video", type=Path)
    ap.add_argument("--industry", default="health_food")
    ap.add_argument("--asr-model", default=None, help="whisper 档位：base/small/medium")
    ap.add_argument("--no-asr", action="store_true", help="跳过口播（只审画面）")
    ap.add_argument("--llm", choices=["auto", "mock", "deepseek"], default="auto")
    ap.add_argument("--background", default="")
    ap.add_argument("--max-ocr", type=int, default=None,
                    help="显式上调 OCR 红线。红线是按 30 秒广告标定的，"
                         "更长的素材需要重新标定——但要**明确地**调，不许静默放行")
    ap.add_argument("--work", type=Path, default=None, help="中间产物目录")
    ap.add_argument("--reuse", action="store_true",
                    help="复用上次的取证结果（work/bundle.json），跳过抽帧/OCR/ASR。"
                         "取证是整条链路里最慢的一段，而调参、换行业、重试 LLM "
                         "都不需要重新识别一遍")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    cfg = settings.pipeline
    work = args.work or (args.video.parent / "_adsure_work")
    cache = Path(work) / "bundle.json"

    if args.reuse and cache.exists():
        bundle = EvidenceBundle.model_validate_json(cache.read_text(encoding="utf-8"))
        print(f"① 复用已有取证结果 {cache}")
        print(f"   {bundle.video.duration:.1f}s · {len(bundle.evidences)} 条证据"
              f"（口播 {len(bundle.texts(EvidenceSource.ASR))} / "
              f"画面 {len(bundle.texts(EvidenceSource.OCR))}）")
        ocr_name, asr_model = "local-rapidocr", "复用"
        return _analyze(args, settings, cfg, bundle, ocr_name, asr_model, cached=True)

    # ── 1. 拆解视频 ───────────────────────────────────────────
    print(f"① 拆解 {args.video.name}")
    ex = extract(args.video, work, cfg)
    print(f"   {ex.meta.duration:.1f}s · {ex.meta.width}x{ex.meta.height} · "
          f"{len(ex.scenes)} 场景 · 采样 {ex.frames_sampled} 帧 → 去重后 "
          f"{len(ex.frames)} 帧（削减 {ex.dedup_ratio*100:.0f}%）")

    # ── 2. OCR ────────────────────────────────────────────────
    scaled = ocr_budget_for(ex.meta.duration, cfg.max_ocr_calls_per_video)
    max_ocr = args.max_ocr or scaled
    if args.max_ocr:
        print(f"   ⚠️ OCR 红线由 {scaled} 显式上调为 {max_ocr}")
    elif scaled != cfg.max_ocr_calls_per_video:
        print(f"   OCR 红线按时长折算：{cfg.max_ocr_calls_per_video}（30s 基准）"
              f" → {scaled}（本片 {ex.meta.duration:.1f}s），每秒成本不变")
    ocr = LocalRapidOCR(max_calls=max_ocr)
    print(f"② OCR {len(ex.frames)} 帧（{ocr.name}）")
    try:
        ocr_ev = ocr.recognize(ex.frames, ex.meta.width, ex.meta.height)
    except CostLimitExceeded as e:
        print(f"\n✗ 触发成本红线，已停止（这是设计行为，不是故障）：\n{e}")
        print("确认素材合理后，用 --max-ocr 显式上调。")
        raise SystemExit(2)
    print(f"   得到 {len(ocr_ev)} 条画面文字")

    # ── 3. ASR ────────────────────────────────────────────────
    asr_ev = []
    if not args.no_asr and ex.audio_path:
        asr = LocalWhisperASR(model_size=args.asr_model)
        print(f"③ ASR（{asr.name} / {asr.model_size}）")
        asr_ev = asr.transcribe(ex.audio_path)
        nw = sum(len(e.word_timings) for e in asr_ev)
        print(f"   得到 {len(asr_ev)} 段口播，共 {nw} 个字级时间戳")
    else:
        print("③ ASR 跳过 —— 报告中必须声明「本次未审核口播内容」")

    bundle = EvidenceBundle(
        review_id=args.video.stem,
        video=ex.meta,
        evidences=asr_ev + ocr_ev,
        cost=CostRecord(asr_calls=1 if asr_ev else 0, ocr_calls=ocr.calls_used,
                        frames_sampled=ex.frames_sampled,
                        frames_after_dedup=len(ex.frames)),
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    print(f"   取证结果已缓存：{cache}（下次加 --reuse 可跳过取证）")

    return _analyze(args, settings, cfg, bundle, ocr.name,
                    (asr.model_size if asr_ev else None), cached=False)


def _analyze(args, settings, cfg, bundle, ocr_name, asr_model, cached: bool) -> None:
    """取证之后的部分。单独拆出来，是为了让复用缓存时走完全同一段代码 ——
    两条路径各写一份迟早会漂移。"""
    # ── 4. 合并 + 找法 ────────────────────────────────────────
    before = len(bundle.texts(EvidenceSource.OCR))
    bundle.evidences = merge_ocr(list(bundle.evidences), cfg)
    after = len(bundle.texts(EvidenceSource.OCR))
    print(f"④ 字幕跨帧合并：{before} → {after} 条")

    matcher = load_default_matcher()
    hits = matcher.match_bundle(bundle, industry=args.industry)
    mand = MandatoryChecker().check_bundle(bundle, industry=args.industry)
    print(f"⑤ 找法：违禁词命中 {len(hits)} 条 · 必备要素核查 {len(mand)} 条")
    for h in hits:
        src = "口播" if h.source == EvidenceSource.ASR else "画面"
        print(f"   [{h.t_start:6.2f}s → {h.t_end:6.2f}s] {src} 「{h.matched_text}」 [{h.entry.level}]")

    # ── 5. 涵摄 ───────────────────────────────────────────────
    if args.llm == "mock":
        llm, mode = MockLLMProvider(), "mock"
    elif args.llm == "deepseek":
        llm, mode = get_llm_provider("deepseek"), "deepseek"
    elif settings.llm_configured:
        llm, mode = get_llm_provider(), settings.llm_provider
    else:
        llm, mode = MockLLMProvider(), "mock"

    print(f"⑥ 涵摄推理（模型 = {mode}）")
    subsumer = Subsumer(llm=llm)
    report = Report(review_id=bundle.review_id, video_path=bundle.video.path,
                    duration=bundle.video.duration)
    for h in hits:
        sub, cases = subsumer.subsume_hit(h, background=args.background,
                                          industry=args.industry)
        report.findings.append(finding_from_hit(h, sub, cases))
        print(f"   {h.matched_text} → {sub.verdict.value}")
    for f in mand:
        report.findings.append(finding_from_mandatory(f))

    print(f"\n整体风险等级：{report.level.label}"
          f"　│　风险 {len(report.risks)} 条　│　仅提示 {len(report.advisories)} 条")
    usage = getattr(llm, "usage_summary", lambda: "")()
    if usage:
        print(usage)

    # ── 6. 导出 ───────────────────────────────────────────────
    if args.out:
        has_asr = bool(bundle.texts(EvidenceSource.ASR))
        asr_note = "" if has_asr else "；⚠️ 本次未审核口播内容"
        payload = {
            "meta": {
                "review_id": report.review_id,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "industry": args.industry,
                "video": {"path": str(args.video.name),
                          "duration": bundle.video.duration,
                          "width": bundle.video.width, "height": bundle.video.height},
                "llm": {"mode": mode, "is_real": mode != "mock", "usage": usage},
                "lexicon_reviewed_by_legal": bool(
                    getattr(getattr(matcher, "lexicon", None), "reviewed_by_legal", False)),
                "data_source": f"真实视频 · 本地模型取证（OCR {ocr_name}"
                               + (f" / ASR {asr_model}" if has_asr and asr_model else "")
                               + ")" + asr_note,
            },
            "summary": {"level": report.level.value, "level_label": report.level.label,
                        "risk_count": len(report.risks),
                        "advisory_count": len(report.advisories)},
            "cost": {"frames_sampled": bundle.cost.frames_sampled,
                     "frames_after_dedup": bundle.cost.frames_after_dedup,
                     "dedup_ratio": round(bundle.cost.dedup_ratio, 4),
                     "ocr_calls": bundle.cost.ocr_calls,
                     "asr_calls": bundle.cost.asr_calls},
            "evidence": _evidence_json(bundle),
            "findings": _findings_json(report),
            "disclaimer": DISCLAIMER,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"报告已导出：{args.out}")


if __name__ == "__main__":
    main()
