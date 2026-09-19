# -*- coding: utf-8 -*-
"""Generic high-confidence paths derived from content and evidence context."""

import re


FALSE_ADVERTISING_GENERAL = (
    "TRUTHFULNESS.MISLEADING_OMISSION.FALSE_ADVERTISING_GENERAL"
)
CITATION_SOURCE_SCOPE = (
    "EVIDENCE_FACT.DATA_CITATION."
    "CITATION_LACKS_SOURCE_SCOPE_OR_VALIDITY"
)
ENDORSEMENT_PROHIBITED_SUBJECT = "ENDORSEMENT.PROHIBITED_SUBJECT"
ENDORSEMENT_PROHIBITED_CATEGORY = (
    "ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY"
)
ENDORSEMENT_ACTUAL_USE = (
    "ENDORSEMENT.ACTUAL_USE_DUTY."
    "ENDORSER_RECOMMENDS_WITHOUT_ACTUAL_USE"
)
MINOR_ANTI_ADDICTION = (
    "MINORS_PUBLIC_ORDER.MINOR_PAYMENT."
    "MINOR_ANTI_ADDICTION_CIRCUMVENTION"
)
ADVERTISER_QUALIFICATION = (
    "SCOPE_ACCESS.SUBJECT_QUALIFICATION."
    "ADVERTISER_QUALIFICATION_FALSE_OR_INVALID"
)


def _available_paths(pruned_tree):
    return {
        level_3.get("issue_id")
        for level_1 in pruned_tree.get("branches") or []
        for level_2 in level_1.get("children") or []
        for level_3 in level_2.get("children") or []
        if level_3.get("issue_id")
    }


def _path_ancestry(pruned_tree):
    return {
        level_3.get("issue_id"): (level_1.get("issue_id"), level_2.get("issue_id"))
        for level_1 in pruned_tree.get("branches") or []
        for level_2 in level_1.get("children") or []
        for level_3 in level_2.get("children") or []
        if level_3.get("issue_id")
    }


def _first_signal(text, signals):
    return next((signal for signal in signals if signal in text), "")


def _path_item(
    issue_id,
    policy_id,
    content_evidence,
    context_evidence="",
    outcome="direct",
):
    return {
        "level_1_issue_id": issue_id.split(".", 1)[0],
        "level_2_issue_id": issue_id.rsplit(".", 1)[0],
        "level_3_issue_id": issue_id,
        "trigger_source": "mixed" if context_evidence else "content",
        "content_evidence": content_evidence,
        "context_evidence": context_evidence,
        "reason": "明确文案信号与背景证据共同触发高置信问题路径保留",
        "suggested_outcome": outcome,
        "confidence": 1.0,
        "targeted_path_policy_id": policy_id,
        "targeted_path_priority_applied": True,
    }


def generic_issue_paths(context_package, pruned_tree):
    available = _available_paths(pruned_tree)
    ancestry = _path_ancestry(pruned_tree)
    content = str(context_package.get("material_text") or "")
    background = str(context_package.get("supplemental_background") or "")
    industry = str(context_package.get("industry") or "")
    category = str(context_package.get("product_category") or "")
    combined = f"{content} {background}"
    result = []

    recommender = _first_signal(
        content,
        ("专家", "医生", "医师", "院士", "明星", "代言", "推荐", "背书"),
    )
    missing_endorsement_proof = _first_signal(
        background,
        ("未提供", "缺少", "无授权", "无法核验", "没有"),
    )
    restricted_category = any(
        signal in f"{industry} {category}"
        for signal in ("保健食品", "食品", "药品", "医疗器械")
    )
    if recommender and missing_endorsement_proof:
        if restricted_category:
            for issue_id, policy_id in (
                (ENDORSEMENT_PROHIBITED_SUBJECT, "restricted-endorser-subject-v1"),
                (
                    ENDORSEMENT_PROHIBITED_CATEGORY,
                    "restricted-category-recommender-v1",
                ),
            ):
                if issue_id in available:
                    result.append(_path_item(
                        issue_id,
                        policy_id,
                        recommender,
                        missing_endorsement_proof,
                    ))
        if ENDORSEMENT_ACTUAL_USE in available:
            result.append(_path_item(
                ENDORSEMENT_ACTUAL_USE,
                "endorser-actual-use-proof-v1",
                recommender,
                missing_endorsement_proof,
                outcome="fact_check",
            ))

    data_signal = ""
    data_match = re.search(
        r"(?:\d+(?:\.\d+)?%|\d+天|临床(?:验证|试验)|用户(?:有效|好评)|"
        r"统计(?:数据|资料)|调查结果)",
        content,
    )
    if data_match:
        data_signal = data_match.group(0)
    missing_data_context = _first_signal(
        background,
        (
            "未提供数据来源",
            "未注明来源",
            "未标明出处",
            "未提供统计",
            "未提供试验",
            "未提供报告",
            "样本量",
            "统计口径",
            "适用范围",
        ),
    )
    if data_signal and missing_data_context and CITATION_SOURCE_SCOPE in available:
        result.append(_path_item(
            CITATION_SOURCE_SCOPE,
            "data-citation-source-scope-v1",
            data_signal,
            missing_data_context,
            outcome="fact_check",
        ))

    effect_truthfulness_signal = _first_signal(
        content,
        ("永不反弹", "永久有效", "效果永久", "彻底根治"),
    )
    if (
        data_signal
        and missing_data_context
        and effect_truthfulness_signal
        and FALSE_ADVERTISING_GENERAL in available
    ):
        result.append(_path_item(
            FALSE_ADVERTISING_GENERAL,
            "unsubstantiated-effect-truthfulness-v1",
            effect_truthfulness_signal,
            missing_data_context,
        ))

    probability_hype = _first_signal(
        content,
        ("高概率", "必得", "必中", "百分百抽中", "仅此一次"),
    )
    probability_fact = re.search(r"\d+(?:\.\d+)?%|概率|保底", background)
    if (
        probability_hype
        and probability_fact
        and FALSE_ADVERTISING_GENERAL in available
    ):
        result.append(_path_item(
            FALSE_ADVERTISING_GENERAL,
            "probability-truthfulness-v1",
            probability_hype,
            probability_fact.group(0),
        ))

    no_real_name = _first_signal(
        content,
        ("不需要实名认证", "无需实名认证", "免实名认证", "无需实名", "游客模式"),
    )
    if no_real_name and MINOR_ANTI_ADDICTION in available:
        result.append(_path_item(
            MINOR_ANTI_ADDICTION,
            "game-real-name-bypass-v1",
            no_real_name,
        ))

    no_license = _first_signal(
        combined,
        ("无版号", "未取得版号", "没有版号", "版号无效", "版号造假"),
    )
    if no_license and ADVERTISER_QUALIFICATION in available:
        result.append(_path_item(
            ADVERTISER_QUALIFICATION,
            "game-license-qualification-v1",
            _first_signal(content, ("无版号", "版号无效", "版号造假")),
            _first_signal(background, ("未取得版号", "没有版号", "版号无效")),
            outcome="fact_check",
        ))

    for item in result:
        parents = ancestry.get(item.get("level_3_issue_id"))
        if parents:
            item["level_1_issue_id"], item["level_2_issue_id"] = parents
    return result
