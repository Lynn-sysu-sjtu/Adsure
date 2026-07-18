# -*- coding: utf-8 -*-
"""Review helpers for v5 rule fields used by app_kg.py."""

import re


APPLICABILITY_OPTIONS = ["明确适用型", "关系判断型", "开放解释型"]
DEPENDENCY_OPTIONS = ["low", "medium", "high"]
ROUTE_OPTIONS = ["operator_direct", "operator_supply_docs", "legal_review_required"]
ROUTE_STATUS_OPTIONS = ["provisional", "finalized"]


def split_list_text(value):
    if not value:
        return []
    parts = re.split(r"[,，\n]+", str(value))
    return [part.strip() for part in parts if part.strip()]


def normalize_v5_review_fields(rule, values, reviewer, now):
    applicability = rule.setdefault("rule_applicability", {})
    applicability["type"] = values["applicability_type"]
    applicability["reason"] = values.get("applicability_reason") or None

    routing = rule.setdefault("routing", {})
    routing["interpretation_dependency"] = values["interpretation_dependency"]
    routing["fact_dependency"] = values["fact_dependency"]
    routing["misjudgment_cost"] = values["misjudgment_cost"]
    routing["default_route"] = values["default_route"]
    routing["route_reason"] = values.get("route_reason") or None
    routing["route_status"] = values["route_status"]
    override = routing.setdefault("route_override", {})
    override["enabled"] = bool(values.get("override_enabled", False))
    override["reason"] = values.get("override_reason") or None
    override["reviewer"] = reviewer if override["enabled"] else None
    override["review_date"] = now if override["enabled"] else None

    fact_check = rule.setdefault("fact_check", {})
    fact_check["future_required"] = bool(values.get("fact_future_required", False))
    fact_check["current_required"] = bool(values.get("fact_current_required", False))
    fact_check["required_materials"] = split_list_text(values.get("required_materials_text"))
    fact_check["data_sources"] = split_list_text(values.get("data_sources_text"))
    fact_check["note"] = values.get("fact_note") or None

    # Keep legacy rag fields synchronized for older audit code and files.
    rag = rule.setdefault("rag", {})
    rag["future_fact_rag"] = fact_check["future_required"]
    rag["fact_rag_note"] = fact_check["note"]

