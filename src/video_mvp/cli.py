from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import analyze_video


def main() -> None:
    parser = argparse.ArgumentParser(description="审心 Adsure 视频广告合规审核 MVP")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--industry", choices=["一般行业", "保健食品", "普通食品", "化妆品", "教育培训", "金融投资", "医疗", "药品", "医疗器械"], default="一般行业")
    parser.add_argument("--product-category", default="")
    parser.add_argument("--platform", default="")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--transcript-text", default="")
    parser.add_argument("--sample-interval", type=float, default=0.5)
    parser.add_argument("--max-frames", type=int, default=1800)
    parser.add_argument("--asr", choices=["auto", "off"], default="auto")
    parser.add_argument("--sampling", choices=["adaptive", "uniform"], default="adaptive")
    parser.add_argument("--semantics", choices=["auto", "off"], default="auto")
    parser.add_argument("--proof", type=Path, action="append", default=[])
    parser.add_argument("--product-name", default="")
    parser.add_argument("--product-id", default="")
    parser.add_argument("--activity-text", default="")
    parser.add_argument("--landing-page-text", default="")
    parser.add_argument("--allow-cloud", action="store_true",help="明确允许本次视频最多12张代表帧及对应机器口播发送至私密配置中的云端地址；不发送完整视频或材料")
    args = parser.parse_args()
    from .cloud_config import config
    report = analyze_video(
        args.video,
        args.output,
        industry=args.industry,
        product_category=args.product_category,
        platform=args.platform,
        transcript_path=args.transcript,
        transcript_text=args.transcript_text,
        sample_interval=args.sample_interval,
        max_frames=args.max_frames,
        asr_mode=args.asr,
        sampling_strategy=args.sampling,
        semantic_mode=args.semantics, proof_paths=args.proof, product_name=args.product_name, product_id=args.product_id,
        activity_text=args.activity_text, landing_page_text=args.landing_page_text,
        cloud_consent_endpoint=config().endpoint if args.allow_cloud else "",
    )
    print(json.dumps({
        "report": report["artifact_paths"]["report"],
        "review_status": report["review_status"],
        "coverage_status": report["coverage_status"],
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
