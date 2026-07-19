# -*- coding: utf-8 -*-
"""Stable internal identity helpers for dual-ID rule assets."""


def rule_identity(rule):
    """Return the globally unique UID, with legacy ID as migration fallback."""
    if not isinstance(rule, dict):
        return None
    return rule.get("rule_uid") or rule.get("rule_id")
