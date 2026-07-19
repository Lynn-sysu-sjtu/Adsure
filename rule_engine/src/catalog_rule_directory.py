# -*- coding: utf-8 -*-
"""Build the compact allow-listed rule directory used by catalog recall."""

from rule_identity import rule_identity


DIRECTORY_FIELDS = (
    "rule_uid",
    "rule_id",
    "title",
    "dimension",
    "catalog_text",
    "catalog_group",
    "trigger_layer",
)


def _trigger_layer(rule):
    recall = rule.get("recall", {}) or {}
    return recall.get("trigger_layer") or rule.get("trigger_layer")


def build_catalog_directory(rules, request=None):
    """Return only explicitly enabled open-ended content rules."""
    directory = []
    seen_ids = set()
    for rule in rules:
        recall = rule.get("recall", {}) or {}
        identity = rule_identity(rule)
        rule_id = rule.get("rule_id")
        if not recall.get("catalog_recall_enabled"):
            continue
        if _trigger_layer(rule) != "content":
            continue
        if not identity or identity in seen_ids:
            continue
        catalog_text = str(recall.get("catalog_text") or "").strip()
        catalog_group = str(recall.get("catalog_group") or "").strip()
        if not catalog_text or not catalog_group:
            continue
        seen_ids.add(identity)
        directory.append(
            {
                "rule_uid": rule.get("rule_uid"),
                "rule_id": rule_id,
                "title": rule.get("title"),
                "dimension": rule.get("dimension"),
                "catalog_text": catalog_text,
                "catalog_group": catalog_group,
                "trigger_layer": "content",
            }
        )
    return directory
