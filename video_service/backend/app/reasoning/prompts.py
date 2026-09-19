"""涵摄推理的提示词构造。

三条硬约束，写进提示词也写进测试：

  ① **三限定输入** —— 只给证据原文、补充背景、召回的规则与法条原文。
     法条由规则引擎提供，模型不得自行寻找或生成法条。

  ② **只答要件，不下结论** —— 模型逐条回答构成要件的事实问题，
     最终定性由代码推导。不给它「是否违规」这个问题。

  ③ **「无法判断」是正当答案** —— 依赖素材之外事实的要件，
     必须允许模型说「判断不了」。逼它二选一只会得到编造的确定性。
"""

from __future__ import annotations

import json

from app.reasoning.schema import RuleSpec

SYSTEM = """你是广告合规审核的法律推理助手，负责法律三段论中的「涵摄」环节：\
判断给定的广告事实是否满足指定法条的各项构成要件。

严格遵守：
1. 只使用下方提供的法条原文。**不得引用、补充或生成任何未提供的法条**。
2. 只回答每一项构成要件的事实问题，**不要给出「是否违规」的整体结论** —— \
定性由系统根据你的要件答案推导。
3. 每项只能答 yes（要件成立）、no（要件不成立）、uncertain（依赖广告素材之外的\
事实，仅凭素材无法判断）。
4. **uncertain 是正当答案**，不是失败。拿不准就答 uncertain，不要猜。\
但 uncertain 专指「需要素材之外的材料才能判断」，不是「我不太确定」。
5. 每项都要给 reason，**必须引用素材原文或明确指出素材中缺少什么**，不得空泛。

只输出 JSON，不要任何解释性文字。"""


def _format_evidence(payload: dict) -> str:
    lines = []
    for k, v in payload.items():
        if k in {"法条原文", "判定要点", "豁免情形核查", "参考类案", "措辞要求"}:
            continue  # 这些放到规则区，避免和事实混在一起
        if isinstance(v, list):
            v = "；".join(str(x) for x in v) or "（无）"
        lines.append(f"  {k}：{v}")
    return "\n".join(lines)


def build_user_prompt(
    rule: RuleSpec,
    evidence_payload: dict,
    background: str = "",
    similar_cases: list[str] | None = None,
) -> str:
    """构造用户提示词。

    素材事实与法律规则**分区呈现**：混在一起时模型容易把规则里的
    例子当成本案事实。这不是理论担心 —— 法条原文里就带着
    「国家级」「最高级」这些词，混排会让模型以为素材里出现了它们。
    """
    elements_json = json.dumps(
        [{"id": e.id, "question": e.question} for e in rule.elements],
        ensure_ascii=False, indent=2,
    )

    parts = [
        "## 一、待审事实（来自广告素材）",
        _format_evidence(evidence_payload),
        "",
        "## 二、运营补充背景",
        (background.strip() or "（运营未提供补充背景。注意：未经核验的说明不构成定案事实。）"),
        "",
        "## 三、适用规则（由规则引擎召回，不得自行补充）",
        f"规则：{rule.name}",
        f"法律依据：{rule.law_ref}",
    ]
    if rule.guideline:
        parts.append(f"配套指南：{rule.guideline}")
    if law_text := evidence_payload.get("法条原文"):
        parts += ["", "法条原文：", str(law_text).strip()]
    if points := evidence_payload.get("判定要点"):
        parts += ["", f"判定要点：{points}"]

    if similar_cases:
        parts += ["", "## 四、相似监管实践（仅供参照，不得作为本案事实依据）"]
        parts += [f"  · {c}" for c in similar_cases]

    parts += [
        "",
        "## 五、请逐项判断以下构成要件",
        elements_json,
        "",
        "输出 JSON，格式如下（elements 的条数与顺序必须与上面一致）：",
        json.dumps({
            "elements": [
                {"id": "要件id", "answer": "yes|no|uncertain", "reason": "引用素材原文说明"}
            ]
        }, ensure_ascii=False, indent=2),
    ]
    return "\n".join(parts)
