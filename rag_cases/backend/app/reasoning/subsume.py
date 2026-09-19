"""涵摄执行：调大模型答要件，代码推结论。

LLM Provider 抽象与取证层同构 —— 换 DeepSeek / 豆包只改配置。
另提供一个 Mock，让整条链路在没有 API key 时也能端到端跑通。
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.reasoning.prompts import SYSTEM, build_user_prompt
from app.reasoning.schema import (
    ElementAnswer,
    ElementResult,
    RuleSpec,
    Subsumption,
    load_rules,
)

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


class SubsumptionError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────
#  LLM Provider
# ──────────────────────────────────────────────────────────────


class LLMProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def complete(self, system: str, user: str) -> str: ...


@dataclass
class MockLLMProvider(LLMProvider):
    """按要件 id 返回预设答案，用于链路联调与确定性测试。

    ⚠️ 它**不做任何推理**。默认对每一项都答 uncertain —— 这是诚实的默认值：
    一个不会推理的替身，唯一正确的表态就是「判断不了」。
    默认答 yes 会让演示看起来很成功，实则是拿假结论骗自己。
    """

    name: str = "mock"
    answers: dict[str, tuple[str, str]] | None = None
    """{要件id: (answer, reason)}，未列出的一律 uncertain。"""

    def complete(self, system: str, user: str) -> str:
        ids = re.findall(r'"id":\s*"([^"]+)"', user)
        seen, ordered = set(), []
        for i in ids:
            if i not in seen and i != "要件id":
                seen.add(i)
                ordered.append(i)

        table = self.answers or {}
        return json.dumps({
            "elements": [
                {
                    "id": i,
                    "answer": table.get(i, ("uncertain", ""))[0],
                    "reason": table.get(i, ("uncertain", "Mock 未预设该要件，按无法判断处理"))[1],
                }
                for i in ordered
            ]
        }, ensure_ascii=False)


def get_llm_provider(name: str | None = None) -> LLMProvider:
    from app.config import get_settings

    settings = get_settings()
    name = name or settings.llm_provider

    if name == "mock":
        return MockLLMProvider()

    if name == "deepseek":
        from app.reasoning.llm_deepseek import DeepSeekProvider

        return DeepSeekProvider(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_endpoint,
            model=settings.llm_model,
        )

    raise NotImplementedError(
        f"LLM provider「{name}」尚未实现。当前可用：mock、deepseek。\n"
        "接入其他云端模型时请确认支持稳定的 JSON 输出；"
        "本层依赖结构化回包，自由文本会让要件解析失败。"
    )


# ──────────────────────────────────────────────────────────────
#  涵摄
# ──────────────────────────────────────────────────────────────


class Subsumer:
    def __init__(self, llm: LLMProvider | None = None, cases=None):
        self.llm = llm or get_llm_provider()
        self.rules, self.aliases = load_rules()
        if cases is None:
            from app.reasoning.cases import get_case_library
            cases = get_case_library()
        self.cases = cases

    def resolve_rule(self, rule_id: str) -> RuleSpec | None:
        rid = self.aliases.get(rule_id, rule_id)
        return self.rules.get(rid)

    def _parse(self, raw: str, rule: RuleSpec) -> list[ElementResult]:
        m = _JSON_BLOCK.search(raw or "")
        if not m:
            raise SubsumptionError(f"模型回包里找不到 JSON：{(raw or '')[:200]}")
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError as exc:
            raise SubsumptionError(f"模型回包 JSON 解析失败：{exc}") from exc

        by_id = {str(e.get("id")): e for e in data.get("elements", [])}
        results: list[ElementResult] = []
        for spec in rule.elements:
            item = by_id.get(spec.id)
            if item is None:
                # 缺一项就当无法判断，绝不默认成立。
                # 默认成立等于把模型的沉默当成了肯定答复。
                logger.warning("要件 %s 未被模型回答，按无法判断处理", spec.id)
                results.append(ElementResult(spec, ElementAnswer.UNCERTAIN,
                                             "模型未回答该要件"))
                continue
            try:
                answer = ElementAnswer(str(item.get("answer", "")).strip().lower())
            except ValueError:
                logger.warning("要件 %s 返回了非法答案 %r，按无法判断处理",
                               spec.id, item.get("answer"))
                answer = ElementAnswer.UNCERTAIN
            results.append(ElementResult(spec, answer, str(item.get("reason", "")).strip()))
        return results

    def subsume(
        self,
        rule_id: str,
        evidence_payload: dict,
        background: str = "",
        similar_cases: list[str] | None = None,
    ) -> Subsumption | None:
        """对一条命中做涵摄。规则未定义要件时返回 None（由调用方决定如何呈现）。"""
        rule = self.resolve_rule(rule_id)
        if rule is None:
            logger.warning("规则 %s 尚未定义构成要件，跳过涵摄", rule_id)
            return None

        user = build_user_prompt(rule, evidence_payload, background, similar_cases)
        raw = self.llm.complete(SYSTEM, user)
        results = self._parse(raw, rule)
        return Subsumption.derive(rule, results)

    def subsume_hit(self, hit, background: str = "", industry: str | None = None):
        """对一条违禁词命中做涵摄，并自动检索类案。

        返回 (Subsumption | None, 类案列表)。类案单独返回而不是塞进 Subsumption，
        是因为它**不参与定性** —— 别的公司被罚过不构成本案的事实认定，
        类案只帮人理解监管口径。混进定性链路就成了「别人被罚所以你也违规」。
        """
        rule_id = getattr(hit.entry, "rule_id", "") or self._fallback_rule_id(hit)
        scored = []
        if self.cases is not None and getattr(self.cases, "available", False):
            scored = self.cases.retrieve(
                term=hit.matched_text,
                rule_id=rule_id,
                industry=industry,
                linked_case_ids=tuple(getattr(hit.entry, "cases", ()) or ()),
            )
        lines = self.cases.format_for_prompt(scored) if scored else []
        sub = self.subsume(rule_id, hit.to_llm_payload(), background, lines)
        return sub, scored

    @staticmethod
    def _fallback_rule_id(hit) -> str:
        """词条没写 rule_id 时按层级兜底。"""
        return "ADLAW-009-03" if getattr(hit.entry, "level", "") == "L1" else "ADLAW-017"
