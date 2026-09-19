"""涵摄推理的数据结构与定性逻辑。

核心设计：**最终定性由代码从要件推导，不问大模型。**

大模型只回答要件层面的事实问题（是 / 否 / 依赖未提供的事实），
三段论的结论由 `Subsumption.derive()` 按逻辑算出。这样：

  · 模型越不过要件直接下结论
  · 不会出现「要件都不成立但结论是违规」这类自相矛盾
  · 结论能追溯到具体是哪一条要件出的问题，法务可追问

如果把定性也交给模型，上面三条一条都保不住。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml

ELEMENTS_PATH = Path(__file__).parent / "elements.yaml"


class ElementAnswer(StrEnum):
    YES = "yes"
    NO = "no"
    UNCERTAIN = "uncertain"
    """依赖广告素材之外的事实，仅凭素材无法判断。**不是「大概吧」**。"""

    @property
    def label(self) -> str:
        return {"yes": "成立", "no": "不成立", "uncertain": "无法从素材判断"}[self.value]


class Verdict(StrEnum):
    VIOLATION = "violation"
    NOT_APPLICABLE = "not_applicable"
    NEEDS_FACTS = "needs_facts"

    @property
    def label(self) -> str:
        return {
            "violation": "存在违规风险",
            "not_applicable": "本条不适用",
            "needs_facts": "需事实核验",
        }[self.value]


@dataclass(frozen=True)
class ElementSpec:
    id: str
    question: str
    required: bool = True
    if_not: str = ""
    needs_material: bool = False
    material_hint: str = ""


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    name: str
    law_ref: str
    elements: tuple[ElementSpec, ...]
    guideline: str = ""


def load_rules(path: Path | None = None) -> tuple[dict[str, RuleSpec], dict[str, str]]:
    raw = yaml.safe_load((path or ELEMENTS_PATH).read_text(encoding="utf-8"))
    rules: dict[str, RuleSpec] = {}
    for rid, item in (raw.get("rules") or {}).items():
        rules[rid] = RuleSpec(
            rule_id=rid,
            name=item["name"],
            law_ref=item["law_ref"],
            guideline=item.get("guideline", ""),
            elements=tuple(
                ElementSpec(
                    id=e["id"],
                    question=e["question"].strip(),
                    required=e.get("required", True),
                    if_not=e.get("if_not", ""),
                    needs_material=e.get("needs_material", False),
                    material_hint=e.get("material_hint", ""),
                )
                for e in item.get("elements", [])
            ),
        )
    return rules, dict(raw.get("rule_aliases") or {})


@dataclass
class ElementResult:
    spec: ElementSpec
    answer: ElementAnswer
    reason: str = ""
    """大模型给出的理由。要引用素材原文，不能空泛。"""


@dataclass
class Subsumption:
    """一次涵摄的完整结果。"""

    rule: RuleSpec
    results: list[ElementResult]
    verdict: Verdict
    blocking_element: ElementResult | None = None
    """决定结论的那一条要件。不适用时是「不成立」的那条，
    需核验时是第一条「无法判断」的那条。违规时为 None。"""

    required_materials: list[str] = field(default_factory=list)

    @classmethod
    def derive(cls, rule: RuleSpec, results: list[ElementResult]) -> Subsumption:
        """从要件答案推导结论。**这里是纯逻辑，没有模型参与。**

        顺序有讲究：先看有没有明确不成立的要件（那就是不适用，最干净的出口），
        再看有没有无法判断的（那是需核验）。反过来会把本可以直接排除的情形
        错误地挂成「待补材料」，白白增加运营的负担。
        """
        for r in results:
            if r.spec.required and r.answer is ElementAnswer.NO:
                return cls(rule, results, Verdict.NOT_APPLICABLE, blocking_element=r)

        uncertain = [r for r in results if r.answer is ElementAnswer.UNCERTAIN]
        if uncertain:
            materials = [
                r.spec.material_hint for r in uncertain if r.spec.material_hint
            ]
            return cls(
                rule, results, Verdict.NEEDS_FACTS,
                blocking_element=uncertain[0],
                required_materials=materials,
            )

        return cls(rule, results, Verdict.VIOLATION)

    @property
    def is_risk(self) -> bool:
        """需核验也算风险 —— 它意味着「尚不能排除」，不是「没问题」。"""
        return self.verdict is not Verdict.NOT_APPLICABLE
