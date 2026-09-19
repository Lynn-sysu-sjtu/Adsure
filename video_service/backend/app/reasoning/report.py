"""六段式风险报告组装。

沿用审心现有的六段结构，视频版每条额外挂时间区间与证据帧：

    ① 风险定性  ② 风险表达  ③ 违规类型
    ④ 法律依据  ⑤ 修改建议  ⑥ 风险定级

⚠️ 措辞边界：本层只做**组装**，不产生新结论。
   定性来自 Subsumption 的推导结果，法条来自规则引擎，
   两者都不在这里被改写 —— 报告层擅自润色是结论失真的常见来源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.reasoning.schema import ElementAnswer, Subsumption, Verdict

DISCLAIMER = (
    "本报告为基于抽帧、语音与画面文字识别、规则库与案例库生成的风险自查线索，"
    "不构成法律意见、合规结论或授权状态证明。系统无法判断使用方是否已取得"
    "相应授权或资质。所有命中与未命中均须人工复核。"
)


class RiskLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ADVISORY = "advisory"

    @property
    def label(self) -> str:
        return {"high": "高", "medium": "中", "low": "低", "advisory": "仅提示"}[self.value]


@dataclass
class Finding:
    """报告里的一条风险。六段齐全，缺一段就不该出现在报告里。"""

    title: str
    t_start: float
    t_end: float
    source: str

    qualification: str      # ① 风险定性
    expression: str         # ② 风险表达
    category: str           # ③ 违规类型
    legal_basis: str        # ④ 法律依据
    suggestion: str         # ⑤ 修改建议
    level: RiskLevel        # ⑥ 风险定级

    frame_ids: list[int] = field(default_factory=list)
    bbox: list[float] | None = None
    required_materials: list[str] = field(default_factory=list)
    element_trace: list[dict] = field(default_factory=list)
    """要件逐项判断的过程。法务追问「为什么是这个结论」时看这里。"""

    similar_cases: list[dict] = field(default_factory=list)
    """相似监管实践。**只帮人理解监管口径，不参与本条的定性**——
    别的公司被罚过不构成本案的事实认定。"""

    counts_as_risk: bool = True

    def to_dict(self) -> dict:
        d = {
            "标题": self.title,
            "时间区间": f"{self.t_start:.2f}s - {self.t_end:.2f}s",
            "来源": self.source,
            "风险定性": self.qualification,
            "风险表达": self.expression,
            "违规类型": self.category,
            "法律依据": self.legal_basis,
            "修改建议": self.suggestion,
            "风险定级": self.level.label,
            "证据帧": self.frame_ids,
        }
        if self.bbox:
            d["画面位置"] = self.bbox
        if self.required_materials:
            d["需补材料"] = self.required_materials
        if self.element_trace:
            d["要件判断过程"] = self.element_trace
        if self.similar_cases:
            d["相似监管实践"] = self.similar_cases
            d["类案说明"] = "仅供理解监管口径参照，不构成对本素材的事实认定。"
        return d


def _trace(sub: Subsumption) -> list[dict]:
    return [
        {"要件": r.spec.id, "问题": r.spec.question, "判断": r.answer.label, "理由": r.reason}
        for r in sub.results
    ]


def _cases_to_dicts(scored) -> list[dict]:
    """类案转报告条目。**已核验与待核验必须分开标注** ——
    把未核验的候选案例当成既定判例写进法律报告是实打实的风险。"""
    out = []
    for s in scored or []:
        c = s.case
        item = {
            "案例": c.title or c.case_id,
            "处罚机关": c.penalty_authority or "—",
            "处罚结果": c.penalty_text or "—",
            "关联理由": s.reason,
            "核验状态": "已核验" if c.verified else "待核验，仅供线索参考",
        }
        if c.source_url:
            item["原文出处"] = c.source_url
        out.append(item)
    return out


def finding_from_hit(hit, sub: Subsumption | None, scored_cases=None) -> Finding:
    """把一条违禁词命中 + 涵摄结果组装成报告条目。

    涵摄缺失（规则尚未定义要件）时**不下定性结论**，
    如实标为「待涵摄」并降级为仅提示 —— 而不是拿粗筛结果当结论。
    粗筛只是「找到嫌疑」，把嫌疑写成风险是这个产品最不能犯的错。
    """
    src = "口播" if str(getattr(hit.source, "value", hit.source)) == "asr" else "画面文字"
    expression = f"{src}中出现「{hit.matched_text}」；上下文：{hit.context}"

    if sub is None:
        return Finding(
            title=f"「{hit.matched_text}」待人工判断",
            t_start=hit.t_start, t_end=hit.t_end, source=src,
            qualification="该表述已被规则库粗筛命中，但对应法条尚未定义构成要件，系统未作涵摄推理。",
            expression=expression,
            category="待补充规则",
            legal_basis=f"{hit.entry.law_ref}（法条原文见规则库）",
            suggestion="请人工判断该表述在本素材语境下是否构成违规。",
            level=RiskLevel.ADVISORY,
            frame_ids=list(hit.frame_ids) if hasattr(hit, "frame_ids") else [],
            similar_cases=_cases_to_dicts(scored_cases),
            counts_as_risk=False,
        )

    if sub.verdict is Verdict.NOT_APPLICABLE:
        blocking = sub.blocking_element
        return Finding(
            title=f"「{hit.matched_text}」经涵摄不适用",
            t_start=hit.t_start, t_end=hit.t_end, source=src,
            qualification=f"经构成要件逐项判断，本条不适用：{blocking.spec.if_not if blocking else ''}",
            expression=expression,
            category="已排除",
            legal_basis=sub.rule.law_ref,
            suggestion="无需整改。",
            level=RiskLevel.LOW,
            element_trace=_trace(sub),
            similar_cases=_cases_to_dicts(scored_cases),
            counts_as_risk=False,
        )

    if sub.verdict is Verdict.NEEDS_FACTS:
        blocking = sub.blocking_element
        return Finding(
            title=f"「{hit.matched_text}」需事实核验",
            t_start=hit.t_start, t_end=hit.t_end, source=src,
            qualification=(
                "法律判断已完成，但其中一项构成要件依赖广告素材之外的事实，"
                f"仅凭素材无法判断：{blocking.spec.question.strip() if blocking else ''}"
            ),
            expression=expression,
            category="需补充材料后复判",
            legal_basis=sub.rule.law_ref,
            # 兜底措辞：要件标了 needs_material 才有清单可给。
            # 没清单时说「请提供下列材料」而后面是空的，等于把问题甩回给运营
            # 却不说要什么 —— 那比不提示还让人恼火。
            suggestion=(
                "请提供下列材料后重新判定；材料齐备则可能排除风险。"
                if sub.required_materials
                else f"该要件无法从素材本身判断，请人工核实后判定：{blocking.spec.question.strip() if blocking else ''}"
            ),
            level=RiskLevel.MEDIUM,
            required_materials=list(sub.required_materials),
            element_trace=_trace(sub),
            similar_cases=_cases_to_dicts(scored_cases),
        )

    level = RiskLevel.HIGH if getattr(hit.entry, "risk", "") == "high" else RiskLevel.MEDIUM
    return Finding(
        title=f"「{hit.matched_text}」存在违规风险",
        t_start=hit.t_start, t_end=hit.t_end, source=src,
        qualification=f"经构成要件逐项判断，{sub.rule.name}各项要件均成立。",
        expression=expression,
        category=sub.rule.name,
        legal_basis=sub.rule.law_ref,
        suggestion=f"建议删除或改写「{hit.matched_text}」相关表述。",
        level=level,
        element_trace=_trace(sub),
        similar_cases=_cases_to_dicts(scored_cases),
    )


def finding_from_mandatory(mf) -> Finding:
    """把 L4 必备要素核查结果组装成报告条目。"""
    ev = mf.evidence
    failed = "；".join(f"{m.name} {m.measured}（要求 {m.threshold}）" for m in mf.failed_measures)

    if ev is not None:
        expression = f"「{ev.text}」出现于 {ev.t_start:.2f}s - {ev.t_end:.2f}s"
        if failed:
            expression += f"；{failed}"
        t0, t1 = ev.t_start, ev.t_end
        frames = list(ev.frame_ids)
        bbox = [ev.bbox.x, ev.bbox.y, ev.bbox.w, ev.bbox.h] if ev.bbox else None
    else:
        expression = "全片未发现该必备表述"
        t0 = t1 = 0.0
        frames, bbox = [], None

    advisory = not mf.counts_as_risk
    return Finding(
        title=f"{mf.requirement.name} —— {mf.status.label}",
        t_start=t0, t_end=t1,
        source="画面文字" if ev is not None else "全片",
        qualification=(
            mf.status.label
            + ("（仅提示，不计入风险数；本项系统无法独立判断是否真的构成问题）"
               if advisory else "")
        ),
        expression=expression,
        category="必备要素与显著性",
        legal_basis=mf.requirement.law_ref,
        suggestion=mf.requirement.remedy or "请人工复核。",
        level=RiskLevel.ADVISORY if advisory else (
            RiskLevel.HIGH if mf.requirement.risk == "high" else RiskLevel.MEDIUM),
        frame_ids=frames, bbox=bbox,
        counts_as_risk=mf.counts_as_risk,
    )


@dataclass
class Report:
    review_id: str
    video_path: str
    duration: float
    findings: list[Finding] = field(default_factory=list)

    @property
    def risks(self) -> list[Finding]:
        return [f for f in self.findings if f.counts_as_risk]

    @property
    def advisories(self) -> list[Finding]:
        return [f for f in self.findings if not f.counts_as_risk]

    @property
    def level(self) -> RiskLevel:
        """整体定级取最严的一条。仅提示项不参与定级。"""
        for lv in (RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW):
            if any(f.level is lv for f in self.risks):
                return lv
        return RiskLevel.ADVISORY

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "物料": self.video_path,
            "时长": f"{self.duration:.1f}s",
            "整体风险等级": self.level.label,
            "风险条数": len(self.risks),
            "仅提示条数": len(self.advisories),
            "风险清单": [f.to_dict() for f in self.findings],
            "免责声明": DISCLAIMER,
        }
