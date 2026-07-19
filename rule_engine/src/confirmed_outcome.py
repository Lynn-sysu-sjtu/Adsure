# -*- coding: utf-8 -*-
"""Deterministic synthesis from validated final subsumption rules."""


RISK_RANK = {"无明显风险": 0, "低": 1, "中": 2, "高": 3}


def _route_for_rule(rule):
    legal_attention = rule.get("legal_attention") or {}
    route = legal_attention.get("default_route") if isinstance(legal_attention, dict) else None
    if route in {"legal_review_required", "法务"}:
        return "法务"
    if route in {"operator_direct", "运营"}:
        return "运营"
    legacy = (rule.get("routing") or {}).get("default_route")
    if legacy in {"legal_review_required", "法务"}:
        return "法务"
    if rule.get("review_required"):
        return "法务"
    if rule.get("applicability_status") == "confirmed_violation" and rule.get("risk_level") == "高":
        return "法务"
    return "运营"


def synthesize_confirmed_outcome(final_rules, llm_risk="无明显风险"):
    final_rules = list(final_rules or [])
    confirmed = [item for item in final_rules if item.get("applicability_status") == "confirmed_violation"]
    fact_rules = [item for item in final_rules if item.get("applicability_status") == "needs_fact_verification"]

    if confirmed:
        opinion_type = "违规修改"
        rule_risk = max((RISK_RANK.get(item.get("risk_level"), 0) for item in confirmed), default=0)
        llm_rank = RISK_RANK.get(llm_risk, 0)
        if llm_rank >= 3:
            risk = "高"
        elif llm_rank >= 2:
            risk = "中"
        elif rule_risk >= 2:
            risk = "中"
        else:
            risk = "低"
    elif fact_rules:
        opinion_type = "需补资料"
        risk = "中"
    else:
        opinion_type = "无明显风险"
        risk = "无明显风险"

    routing = "法务" if any(_route_for_rule(item) == "法务" for item in final_rules) else "运营"
    return {
        "confirmed_rules": confirmed,
        "fact_verification_rules": fact_rules,
        "opinion_type": opinion_type,
        "risk": risk,
        "routing": routing,
    }


def fact_advice_from_final_rules(final_rules):
    missing = []
    for rule in final_rules or []:
        if rule.get("applicability_status") != "needs_fact_verification":
            continue
        for item in rule.get("missing_facts") or []:
            text = str(item).strip()
            if text and text not in missing:
                missing.append(text)
    if not missing:
        return ""
    return "该物料涉及事实/资质/证明材料核验，请运营补充或确认以下材料：" + "；".join(missing)


def _rule_label(rule):
    return f"[{rule.get('rule_id') or 'UNKNOWN'}] {rule.get('title') or '未命名规则'}"


def compose_final_audit_opinion(final_rules, revision_suggestion=""):
    outcome = synthesize_confirmed_outcome(final_rules)
    parts = [f"意见类型：{outcome['opinion_type']}"]
    confirmed = outcome["confirmed_rules"]
    fact_rules = outcome["fact_verification_rules"]

    if confirmed:
        lines = ["【核心违规风险】"]
        for rule in confirmed:
            evidence = rule.get("material_evidence") or "未提供原文证据"
            reason = rule.get("applicability_reason") or "规则构成要件已满足"
            lines.append(f"- {_rule_label(rule)}：{reason}；原文证据：{evidence}")
        parts.append("\n".join(lines))

    if fact_rules:
        lines = ["【附带事实核验】"]
        for rule in fact_rules:
            missing = "、".join(rule.get("missing_facts") or []) or "相关备案、资质或证明材料"
            lines.append(f"- {_rule_label(rule)}：需补充{missing}")
        parts.append("\n".join(lines))

    if revision_suggestion:
        parts.append("【修改建议】\n" + revision_suggestion)
    elif confirmed:
        parts.append("【修改建议】\n请删除或修改构成违规的表达，并保留必要的事实核验材料。")
    elif fact_rules:
        parts.append("【修改建议】\n请补充核验材料后重新提交审核。")

    return "\n\n".join(parts)
