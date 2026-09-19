# -*- coding: utf-8 -*-
"""端到端演示：模拟一条 30 秒保健食品广告，跑通「取证 → 合并 → 找法」。

不需要任何云服务凭证——证据流由 Mock 数据模拟，
目的是验证链路本身是通的，以及报告能不能给出「第几秒、多大、在哪」。

跑法：
    python backend/scripts/demo_pipeline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import PipelineSettings
from app.pipeline.evidence import (
    BBox, CostRecord, EvidenceBundle, EvidenceSource,
    TextEvidence, VideoMeta, WordTiming,
)
from app.pipeline.merge import merge_ocr
from app.reasoning.report import (
    DISCLAIMER, Report, finding_from_hit, finding_from_mandatory,
)
from app.reasoning.subsume import MockLLMProvider, Subsumer
from app.rules.mandatory import MandatoryChecker, MandatoryStatus
from app.rules.matcher import load_default_matcher

W, H = 1920, 1080
CHAR_DUR = 0.22


class DemoLLM(MockLLMProvider):
    """演示用的脚本化替身。

    ⚠️ 它**不做任何推理** —— 按提示词里出现的命中词返回预设答案，
    目的只是让三种定性（违规 / 需事实核验 / 不适用）都能在演示里看到。
    真实模型接入后这个类就该删掉。
    """

    def complete(self, system: str, user: str) -> str:
        import json
        if "国家级" in user or "根治" in user:
            table = {  # 各要件均成立 → 违规
                "points_to_goods": ("yes", "该表述直接修饰所推销的产品配方"),
                "not_time_or_space_order": ("yes", "非时间或空间顺序表述"),
                "not_official_grade": ("yes", "「国家级」不属国家标准等级名称"),
                "lacks_substantiation": ("yes", "素材未提供任何评定依据"),
                "not_medical_ad": ("yes", "本片为保健食品广告，非医疗类广告"),
                "involves_disease_function": ("yes", "「根治老胃病」指向疾病治疗"),
                "is_health_food_ad": ("yes", "标注为保健食品"),
                "beyond_registered_function": ("yes", "「根治胃病」超出增强免疫力的注册功能范围"),
            }
        elif "销量第一" in user:
            table = {  # 举证情况无法从素材判断 → 需事实核验
                "points_to_goods": ("yes", "指向所推销商品的销售状况"),
                "not_time_or_space_order": ("yes", "非顺序表述"),
                "not_official_grade": ("yes", "非国标等级"),
                "lacks_substantiation": ("uncertain", "素材未标注数据来源与统计口径，无法判断有无举证"),
            }
        else:
            table = {}
        self.answers = table
        return super().complete(system, user)


def _rule_id_of(hit) -> str:
    """词条上没写 rule_id 时按层级兜底。L1 一律走绝对化用语。"""
    return "ADLAW-009-03" if getattr(hit.entry, "level", "") == "L1" else "ADLAW-017"


def asr(uid: str, text: str, t0: float) -> TextEvidence:
    timings, t = [], t0
    for ch in text:
        timings.append(WordTiming(text=ch, t_start=t, t_end=t + CHAR_DUR))
        t += CHAR_DUR
    return TextEvidence(id=uid, source=EvidenceSource.ASR, text=text,
                        t_start=t0, t_end=t, word_timings=timings, confidence=0.95)


def ocr(uid: str, text: str, t0: float, t1: float, bbox, frame: int) -> TextEvidence:
    x, y, w, h = bbox
    return TextEvidence(id=uid, source=EvidenceSource.OCR, text=text,
                        t_start=t0, t_end=t1, bbox=BBox(x=x, y=y, w=w, h=h),
                        font_scale=h, confidence=0.92, frame_ids=[frame])


def build_bundle() -> EvidenceBundle:
    """模拟取证层的原始产出：逐帧 OCR，尚未合并。"""
    evidences = [
        # ── 口播 ──
        asr("a1", "本品采用国家级配方", 3.00),
        asr("a2", "上市以来销量第一值得信赖", 20.00),

        # ── 画面花字：一条大字标语，连续 3 个代表帧 ──
        ocr("o1", "全网销量第一", 5.00, 5.50, (0.22, 0.18, 0.55, 0.09), 150),
        ocr("o2", "全网销量第一", 5.50, 6.00, (0.22, 0.18, 0.55, 0.09), 165),
        ocr("o3", "全网销量第一", 6.00, 6.50, (0.22, 0.18, 0.55, 0.09), 180),

        # ── 疾病治疗功效宣称：L2 行业禁用语的典型形态 ──
        ocr("o7", "三天彻底根治老胃病", 8.00, 8.50, (0.20, 0.20, 0.58, 0.09), 240),
        ocr("o8", "三天彻底根治老胃病", 8.50, 9.20, (0.20, 0.20, 0.58, 0.09), 255),

        # ── 画面下方另一条花字（与上一条同时在屏，位置不同）──
        ocr("o4", "限时特惠", 8.00, 8.50, (0.35, 0.72, 0.30, 0.07), 240),

        # ── 右下角的必备声明：又小、又短、又贴边 ──
        #    中间一帧被 OCR 认错了一个字，模拟小字识别不稳
        ocr("o5", "本品不能代替药物", 28.10, 28.30, (0.755, 0.935, 0.205, 0.018), 843),
        ocr("o6", "本品不能代誓药物", 28.30, 28.50, (0.755, 0.935, 0.205, 0.018), 845),
    ]
    return EvidenceBundle(
        review_id="demo-health-food",
        video=VideoMeta(path="秋季新品_保健食品_30s.mp4", duration=30.0,
                        fps=30.0, width=W, height=H),
        evidences=evidences,
        cost=CostRecord(asr_calls=1, ocr_calls=7, frames_sampled=75, frames_after_dedup=18),
    )


def rule(title: str = "") -> None:
    print("\n" + "─" * 76)
    if title:
        print(title)
        print("─" * 76)


def main() -> None:
    cfg = PipelineSettings()
    bundle = build_bundle()

    print("=" * 76)
    print(f"  审心 Adsure · 视频合规自查   {bundle.video.path}")
    print(f"  时长 {bundle.video.duration:.0f}s · {bundle.video.width}x{bundle.video.height}")
    print("=" * 76)

    # ── 1. 字幕跨帧合并 ────────────────────────────────────────
    before = len(bundle.texts(EvidenceSource.OCR))
    bundle.evidences = merge_ocr(list(bundle.evidences), cfg)
    after = len(bundle.texts(EvidenceSource.OCR))

    rule("① 字幕跨帧合并")
    print(f"逐帧 OCR {before} 条  →  合并为 {after} 条花字")
    for e in bundle.texts(EvidenceSource.OCR):
        print(f"   [{e.t_start:6.2f}s → {e.t_end:6.2f}s]  时长 {e.duration:4.2f}s  "
              f"字高 {e.font_scale * 100:4.1f}%   {e.text}")

    print(f"\n成本：采样 {bundle.cost.frames_sampled} 帧 → 去重后 "
          f"{bundle.cost.frames_after_dedup} 帧（削减 {bundle.cost.dedup_ratio * 100:.0f}%），"
          f"OCR 调用 {bundle.cost.ocr_calls} 次")

    # ── 2. 违禁词粗筛 ─────────────────────────────────────────
    hits = load_default_matcher().match_bundle(bundle, industry="health_food")

    rule("② 违禁词粗筛（L1 绝对化用语 + L2 行业禁用语）")
    if not hits:
        print("   未命中")
    for h in hits:
        src = "口播" if h.source == EvidenceSource.ASR else "画面"
        print(f"   [{h.t_start:6.2f}s → {h.t_end:6.2f}s] {src}  「{h.matched_text}」  [{h.entry.level}]")
        print(f"      上下文：{h.context}")
        print(f"      依据：  {h.entry.law_ref}")
    print("\n   ↑ 以上为高召回粗筛结果，是否构成违规须经大模型语境复判")

    # ── 3. 必备要素与显著性核查 ───────────────────────────────
    findings = MandatoryChecker().check_bundle(bundle, industry="health_food")

    rule("③ 必备要素与显著性核查（L4）")
    for f in findings:
        if not f.is_risk:
            flag = "○ 通过"
        elif f.counts_as_risk:
            flag = "● 风险"
        else:
            flag = "△ 提示"
        print(f"\n   {flag}  {f.requirement.name} —— {f.status.label}")
        print(f"         依据：{f.requirement.law_ref}")
        if f.evidence is not None:
            print(f"         位置：{f.evidence.t_start:.2f}s → {f.evidence.t_end:.2f}s"
                  f"　原文「{f.evidence.text}」")
        for m in f.measures:
            mark = "✓" if m.passed else "✗"
            print(f"         {mark} {m.name}：{m.measured}（要求 {m.threshold}）")
        if f.status is MandatoryStatus.NOT_SALIENT:
            print(f"         整改：{f.requirement.remedy}")

    # ── 4. 涵摄推理与报告 ─────────────────────────────────────
    subsumer = Subsumer(llm=DemoLLM())
    report = Report(review_id=bundle.review_id, video_path=bundle.video.path,
                    duration=bundle.video.duration)

    for h in hits:
        sub, cases = subsumer.subsume_hit(
            h,
            background="产品已取得保健食品注册证书，功能为增强免疫力。",
            industry="health_food",
        )
        report.findings.append(finding_from_hit(h, sub, cases))
    for f in findings:
        report.findings.append(finding_from_mandatory(f))

    rule("④ 涵摄推理 → 六段式报告")
    print("   ⚠️ 本演示使用脚本化替身代替大模型，要件答案是**预设**的，"
          "不是推理产物。\n      接入真实模型后此处才有实际判断力。\n")

    for f in report.findings:
        badge = {"high": "高", "medium": "中", "low": "低", "advisory": "提示"}[f.level.value]
        print(f"   ── [{badge}] {f.title}　{f.t_start:.2f}s → {f.t_end:.2f}s")
        print(f"      ① 风险定性：{f.qualification}")
        print(f"      ② 风险表达：{f.expression[:64]}")
        print(f"      ③ 违规类型：{f.category}")
        print(f"      ④ 法律依据：{f.legal_basis}")
        print(f"      ⑤ 修改建议：{f.suggestion}")
        print(f"      ⑥ 风险定级：{f.level.label}")
        if f.required_materials:
            print(f"      　 需补材料：{'；'.join(f.required_materials)}")
        if f.element_trace:
            print("      　 要件判断：", end="")
            print("　".join(f"{t['要件']}={t['判断']}" for t in f.element_trace))
        for c in f.similar_cases[:2]:
            print(f"      　 类案参照：{c['案例'][:44]}　{c['处罚结果']}　[{c['核验状态']}]")
        print()

    # ── 小结 ──────────────────────────────────────────────────
    rule("小结")
    print(f"   整体风险等级：{report.level.label}"
          f"　│　风险 {len(report.risks)} 条　│　仅提示 {len(report.advisories)} 条")
    print(f"\n   {DISCLAIMER}")
    print()


if __name__ == "__main__":
    main()
