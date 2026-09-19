# -*- coding: utf-8 -*-
"""High-confidence, signal-based issue paths that must survive LLM variation."""

from issue_tree_generic_path_policy import generic_issue_paths


HEALTH_FOOD_PRE_REVIEW = (
    "SCOPE_ACCESS.AD_REVIEW_ACCESS."
    "PRE_REVIEW_APPROVAL_AND_CONTENT_CONSISTENCY"
)
PRODUCT_QUALIFICATION = (
    "EVIDENCE_FACT.QUALIFICATION_FILING."
    "PRODUCT_QUALIFICATION_MATERIAL_INCOMPLETE_OR_INCONSISTENT"
)
PATENT_NUMBER_TYPE = (
    "IP_PERSONALITY.PATENT_AWARD."
    "PATENT_ADVERTISING_MISSING_PATENT_NUMBER_AND_TYPE"
)
FALSE_ADVERTISING_SPECIFIC_FACTS = (
    "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_SPECIFIC_FACTS"
)


def _available_paths(pruned_tree):
    result = set()
    for level_1 in pruned_tree.get("branches") or []:
        for level_2 in level_1.get("children") or []:
            for level_3 in level_2.get("children") or []:
                result.add(level_3.get("issue_id"))
    return result


def _first_signal(text, signals):
    return next((signal for signal in signals if signal in text), "")


def _path_item(
    issue_id,
    policy_id,
    content_evidence="",
    context_evidence="",
    outcome="fact_check",
):
    level_2 = issue_id.rsplit(".", 1)[0]
    level_1 = issue_id.split(".", 1)[0]
    return {
        "level_1_issue_id": level_1,
        "level_2_issue_id": level_2,
        "level_3_issue_id": issue_id,
        "trigger_source": "mixed",
        "content_evidence": content_evidence,
        "context_evidence": context_evidence,
        "reason": "高置信结构化范围与正文/背景信号触发事实核验路径保留",
        "suggested_outcome": outcome,
        "confidence": 1.0,
        "targeted_path_policy_id": policy_id,
        "targeted_path_priority_applied": True,
    }


def targeted_issue_paths(context_package, pruned_tree):
    available = _available_paths(pruned_tree)
    content = str(context_package.get("material_text") or "")
    background = str(context_package.get("supplemental_background") or "")
    industry = str(context_package.get("industry") or "")
    category = str(context_package.get("product_category") or "")
    combined = content + " " + background
    result = []

    is_health_food = "保健食品" in industry or "保健食品" in category
    if is_health_food and HEALTH_FOOD_PRE_REVIEW in available:
        result.append(_path_item(
            HEALTH_FOOD_PRE_REVIEW,
            "health-food-pre-review-fact-v1",
            content_evidence=_first_signal(content, ("保健食品", "蓝帽")),
        ))
    qualification_signal = _first_signal(
        combined,
        ("蓝帽", "注册", "备案", "认证", "批准文号", "进口报关"),
    )
    product_qualification_signal = _first_signal(
        combined,
        (
            "蓝帽",
            "产品注册",
            "产品备案",
            "注册证",
            "备案凭证",
            "批准文号",
            "进口报关",
            "产品认证",
            "国家认证",
        ),
    )
    missing_proof_signal = _first_signal(
        background,
        ("未提供", "未上传", "缺少", "未取得", "无法核验"),
    )
    if (
        is_health_food
        and product_qualification_signal
        and missing_proof_signal
        and PRODUCT_QUALIFICATION in available
    ):
        result.append(_path_item(
            PRODUCT_QUALIFICATION,
            "health-food-qualification-proof-v1",
            content_evidence=_first_signal(
                content, ("蓝帽", "注册", "备案", "认证", "批准文号", "进口")
            ),
            context_evidence=missing_proof_signal,
        ))
        if FALSE_ADVERTISING_SPECIFIC_FACTS in available:
            result.append(_path_item(
                FALSE_ADVERTISING_SPECIFIC_FACTS,
                "health-food-certification-truthfulness-v1",
                content_evidence=_first_signal(
                    content, ("蓝帽", "注册", "备案", "认证", "批准文号", "进口")
                ),
                context_evidence=missing_proof_signal,
                outcome="direct",
            ))

    patent_signal = _first_signal(content, ("国家专利", "专利技术", "专利配方", "专利"))
    patent_missing_signal = _first_signal(
        background,
        ("未标明专利号", "未标注专利号", "未提供有效专利证书", "专利种类"),
    )
    if patent_signal and patent_missing_signal and PATENT_NUMBER_TYPE in available:
        result.append(_path_item(
            PATENT_NUMBER_TYPE,
            "patent-number-type-disclosure-v1",
            content_evidence=patent_signal,
            context_evidence=patent_missing_signal,
        ))
    existing = {item['level_3_issue_id'] for item in result}
    result.extend(
        item for item in generic_issue_paths(context_package, pruned_tree)
        if item['level_3_issue_id'] not in existing
    )
    return result
