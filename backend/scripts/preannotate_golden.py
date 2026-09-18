# -*- coding: utf-8 -*-
"""金标准预标注：跑一遍审核引擎，把结果转成标注草稿 YAML。

目的：把人工标注从「从零看视频逐条判断」减为「核对/修正机器草稿」。
机器草稿的价值：
  - 时间区间、bbox、命中词已定位好，人工只需确认对不对
  - 漏报（机器没看到的）由人工补——这正是双标的意义
  - 机器的 expected 判断**仅供参考**，标注人必须独立判断后覆盖

⚠️ 纪律（标注手册 §5）：预标注不改变双标要求——两名标注人仍须独立核对，
   不能因为机器给了答案就抄答案。分歧照常留档。

用法：
    python backend/scripts/preannotate_golden.py 视频.mp4 \
        --case-id golden_0001 --industry health_food \
        --annotator 张三 --out datasets/golden/cases/golden_0001.yaml
    # 已有引擎缓存时加 --reuse 跳过取证
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from app.api import run_video_review  # noqa: E402  复用异步 API 的同一条链路

LAYER_BY_CATEGORY = {
    "需补充材料后复判": None,          # 由命中词层级决定，下面按 title 判断
    "必备要素与显著性": "L4",
    "已排除": None,
}
ABSOLUTE_HINTS = ("国家级", "最高级", "最佳", "第一", "最新", "顶级", "独家")


def _layer_of(finding: dict) -> str:
    cat = finding.get("category", "")
    if cat == "必备要素与显著性":
        return "L4"
    blob = finding.get("title", "") + finding.get("报告", {}).get("风险表达", "")
    if any(t in blob for t in ABSOLUTE_HINTS):
        return "L1"
    if any(t in blob for t in ("治疗", "根治", "疗效", "疾病")):
        return "L2"
    if any(t in blob for t in ("专利", "认证", "授权", "独家")):
        return "L3"
    return "L2"


def _expected_of(finding: dict) -> str:
    if not finding.get("counts_as_risk"):
        return "not_applicable"
    if finding.get("required_materials"):
        return "needs_facts"
    return "violation" if finding.get("level") == "high" else "needs_facts"


def build_draft(payload: dict, video_path: Path, case_id: str,
                industry: str, annotator: str) -> dict:
    meta = payload.get("meta", {})
    video_meta = meta.get("video", {})
    sha = hashlib.sha256(video_path.read_bytes()).hexdigest()

    annotations = []
    for i, f in enumerate(payload.get("findings", [])):
        if f.get("t_start") == 0 and f.get("t_end") == 0 and f.get("source") == "全片":
            continue  # 全片缺失项进 mandatory_checks，不进 annotations
        rep = f.get("报告", {})
        ann = {
            "id": f"pa{i+1:02d}",
            "source": "preannotation",   # 标注人核对后改成 both/a/b
            "channel": "asr" if f.get("source") == "口播" else "ocr",
            "t_start": round(float(f.get("t_start", 0)), 2),
            "t_end": round(float(f.get("t_end", 0)), 2),
            "text": rep.get("风险表达", f.get("title", "")),
            "layer": _layer_of(f),
            "expected": _expected_of(f),
            "law_ref": f.get("legal_basis", ""),
            "penalty_case_id": None,
            "uncertain": False,
            "note": f"[机器预标注 {meta.get('llm', {}).get('mode', '?')}] "
                    f"{rep.get('风险定性', '')[:120]}",
        }
        if ann["channel"] == "ocr" and f.get("bbox"):
            b = f["bbox"]
            ann["bbox"] = [round(b["x"], 3), round(b["y"], 3),
                           round(b["w"], 3), round(b["h"], 3)]
        annotations.append(ann)

    mandatory = []
    req_counter = {}
    for i, f in enumerate(payload.get("findings", [])):
        if f.get("category") != "必备要素与显著性":
            continue
        rep = f.get("报告", {})
        # 按标题猜 requirement_id；标注人核对后按实际改
        title = f.get("title", "")
        if "可识别" in title:
            req_id = "ad_identifiability"
        elif "医疗" in title:
            req_id = "medical_device_disclaimer"
        else:
            req_id = "health_food_disclaimer"
        req_counter[req_id] = req_counter.get(req_id, 0) + 1
        m = {
            "id": f"pm{i+1:02d}",
            "requirement_id": req_id,  # 标注人按实际改
            "present": "未发现" not in f.get("title", ""),
            "expected": _expected_of(f),
            "note": f"[机器预标注] {rep.get('风险表达', '')[:150]}",
        }
        if m["present"] and f.get("bbox"):
            b = f["bbox"]
            m["spans"] = [{
                "t_start": round(float(f.get("t_start", 0)), 2),
                "t_end": round(float(f.get("t_end", 0)), 2),
                "bbox": [round(b["x"], 3), round(b["y"], 3),
                         round(b["w"], 3), round(b["h"], 3)],
                "text": rep.get("风险表达", ""),
            }]
            m["observed_font_scale"] = round(b["h"], 3)
        mandatory.append(m)

    return {
        "case_id": case_id,
        "video": {
            "sha256": sha,
            "path": str(video_path),
            "duration_seconds": round(float(video_meta.get("duration", 0)), 1),
            "source": {"type": "preannotation_draft", "url": None,
                       "penalty_case_id": None, "collected_by": annotator},
        },
        "industry": industry,
        "platform": "douyin",
        "background": "",
        "risk_level_overall": {"high": "high", "medium": "medium",
                               "low": "low"}.get(
            payload.get("summary", {}).get("level", ""), "medium"),
        "annotations": annotations,
        "mandatory_checks": mandatory,
        "ip_ground_truth": [],   # IP 标注无机器草稿，人工全标（含负样本）
        "label": {
            "annotator_a": {"name": annotator, "date": date.today().isoformat()},
            "annotator_b": {"name": None, "date": None},
            "disagreements": [],
            "resolved_by": None,
            "status": "draft",
        },
        "_preannotation_meta": {
            "generated_at": meta.get("generated_at"),
            "engine": "evidence-layer-v1",
            "llm_mode": meta.get("llm", {}).get("mode"),
            "cost": payload.get("cost"),
            "warning": "机器草稿仅供核对，标注人必须独立判断；漏报需人工补标",
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="金标准预标注草稿生成")
    ap.add_argument("video", type=Path)
    ap.add_argument("--case-id", required=True)
    ap.add_argument("--industry", default="health_food",
                    choices=["health_food", "cosmetics", "game", "general"])
    ap.add_argument("--annotator", required=True)
    ap.add_argument("--background", default="")
    ap.add_argument("--reuse", action="store_true",
                    help="复用视频旁 _adsure_work/bundle.json 取证缓存")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    payload, _summary = run_video_review(
        args.video, args.video.parent / "_preannotate_work",
        industry=args.industry, background=args.background, llm_mode="mock")

    draft = build_draft(payload, args.video, args.case_id,
                        args.industry, args.annotator)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(draft, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    n_ann = len(draft["annotations"])
    n_man = len(draft["mandatory_checks"])
    print(f"✅ 预标注草稿 → {args.out}")
    print(f"   annotations: {n_ann} 条 | mandatory: {n_man} 条 | IP: 待人工全标")
    print("   下一步：① 校验 python datasets/golden/scripts/validate_golden.py")
    print("         ② 人工核对每条（改 source 为 a/b、修正 expected、补漏报）")
    print("         ③ 第二标注人独立标注后合并")


if __name__ == "__main__":
    main()
