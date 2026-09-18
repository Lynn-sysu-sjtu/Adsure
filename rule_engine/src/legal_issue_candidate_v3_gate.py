# -*- coding: utf-8 -*-
"""Deterministic evidence gate for DeepSeek proactive-check candidates."""

import re


ALLOWED_CORE_SUPPORT_FIELDS = {
    "title",
    "legal_basis",
    "applies_to",
    "rule_applicability",
}

PROACTIVE_TOPIC_MARKERS = (
    "概率", "抽卡", "掉落", "爆率", "版号", "未成年人", "充值", "付费",
    "美白", "祛斑", "防脱", "特殊化妆品", "注册证", "备案",
    "疾病", "治疗", "预防", "药物", "降血糖", "降血压", "警示语",
    "数据", "实验", "检测", "代言", "赠送", "福利", "奖励品",
)


def _normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _string_values(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _string_values(nested)


def validate_candidate_core_support(candidate, rule):
    """Return validation errors for unsupported proactive-check evidence."""
    proactive = candidate.get("proactive_check")
    if proactive is None:
        return []
    if not isinstance(proactive, dict):
        return ["proactive_check must be an object or null"]

    support = proactive.get("core_support")
    if not isinstance(support, list) or not support:
        return ["proactive_check.core_support must be a non-empty array"]

    errors = []
    required_text = ("check_key", "name", "requirement")
    for key in required_text:
        if not isinstance(proactive.get(key), str) or not proactive[key].strip():
            errors.append(f"proactive_check.{key} must be a non-empty string")
    if proactive.get("check_type") not in {
        "fact_verification", "qualification", "disclosure", "workflow"
    }:
        errors.append("proactive_check.check_type is invalid")
    if proactive.get("default_severity") not in {"高", "中", "低"}:
        errors.append("proactive_check.default_severity is invalid")
    applicability = proactive.get("applicability")
    if not isinstance(applicability, dict):
        errors.append("proactive_check.applicability must be an object")
    else:
        for key in ("industries", "platforms", "material_types"):
            values = applicability.get(key)
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                errors.append(f"proactive_check.applicability.{key} must be a string array")
    conditions = proactive.get("trigger_conditions")
    if not isinstance(conditions, dict):
        errors.append("proactive_check.trigger_conditions must be an object")
    else:
        for key in ("all", "any", "exclude"):
            values = conditions.get(key)
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                errors.append(f"proactive_check.trigger_conditions.{key} must be a string array")
    materials = proactive.get("required_materials")
    if not isinstance(materials, list) or not all(isinstance(item, str) for item in materials):
        errors.append("proactive_check.required_materials must be a string array")
    for index, item in enumerate(support):
        path = f"proactive_check.core_support[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path} must be an object")
            continue
        source_field = item.get("source_field")
        evidence = _normalize_whitespace(item.get("evidence"))
        if source_field not in ALLOWED_CORE_SUPPORT_FIELDS:
            errors.append(f"{path}.source_field is not an allowed core field")
            continue
        if not evidence:
            errors.append(f"{path}.evidence must be non-empty")
            continue
        source_values = [_normalize_whitespace(value) for value in _string_values(rule.get(source_field))]
        if not any(evidence in value for value in source_values):
            errors.append(f"{path}.evidence is not an exact quote from {source_field}")

    check_text = " ".join(_normalize_whitespace(value) for value in _string_values({
        "name": proactive.get("name"),
        "trigger_conditions": proactive.get("trigger_conditions"),
        "requirement": proactive.get("requirement"),
        "required_materials": proactive.get("required_materials"),
    }))
    core_text = " ".join(
        _normalize_whitespace(value)
        for field in ALLOWED_CORE_SUPPORT_FIELDS
        for value in _string_values(rule.get(field))
    )
    unsupported = sorted({
        marker for marker in PROACTIVE_TOPIC_MARKERS
        if marker in check_text and marker not in core_text
    })
    if unsupported:
        errors.append("unsupported proactive topic markers: " + ", ".join(unsupported))
    return errors
