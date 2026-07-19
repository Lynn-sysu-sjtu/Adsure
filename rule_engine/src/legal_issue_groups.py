# -*- coding: utf-8 -*-
"""Load, validate, and select representatives from legal-issue groups."""

import json
from pathlib import Path

from rule_identity import rule_identity


AUTHORITY_RANK = {
    "法律": 60,
    "行政法规": 50,
    "部门规章": 40,
    "法规": 40,
    "规范性文件": 30,
    "行业规范": 20,
    "平台规则": 10,
}


def load_legal_issue_groups(base_dir):
    path = Path(base_dir) / "assets" / "legal_issue_groups.json"
    if not path.exists():
        return {"groups": []}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _trigger_layer(rule):
    recall = rule.get("recall") or {}
    return recall.get("trigger_layer") or rule.get("trigger_layer") or "content"


def validate_legal_issue_groups(asset, rules):
    known = {rule_identity(rule): rule for rule in rules if rule_identity(rule)}
    seen_groups = set()
    membership = {}
    for group in asset.get("groups", []) or []:
        group_id = str(group.get("issue_group_id") or "").strip()
        if not group_id or group_id in seen_groups:
            raise ValueError(f"Invalid or duplicate issue_group_id: {group_id}")
        seen_groups.add(group_id)
        policy = group.get("selection_policy") or {}
        if policy:
            if policy.get("primary_rule_strategy") != "highest_legal_authority" or policy.get("platform_rule_strategy") != "current_platform_only":
                raise ValueError(f"Invalid selection_policy in legal issue group: {group_id}")
            for limit_name in ("max_primary_rules", "max_platform_rules"):
                value = policy.get(limit_name, 1)
                if not isinstance(value, int) or value < 1:
                    raise ValueError(f"Invalid {limit_name} in legal issue group: {group_id}")
        layers = set()
        for uid in group.get("member_rule_uids", []) or []:
            if uid not in known:
                raise ValueError(f"Unknown rule_uid in legal issue group: {uid}")
            if uid in membership:
                raise ValueError(f"rule_uid belongs to multiple legal issue groups: {uid}")
            membership[uid] = group_id
            layers.add(_trigger_layer(known[uid]))
        if len(layers) > 1:
            raise ValueError(f"Mixed trigger_layer values in legal issue group: {group_id}")
    return True


def legal_issue_group_index(asset):
    return {
        uid: group
        for group in asset.get("groups", []) or []
        for uid in group.get("member_rule_uids", []) or []
    }


def _platform_values(rule):
    value = rule.get("platform")
    if value in (None, ""):
        value = (rule.get("applies_to") or {}).get("platforms")
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    text = str(value or "").strip().lower()
    return {text} if text else set()


def _specificity(rule):
    industries = (rule.get("applies_to") or {}).get("industries") or []
    if not isinstance(industries, list):
        industries = [industries]
    return -len([item for item in industries if str(item).strip()])


def _selection_key(rule):
    return (
        -AUTHORITY_RANK.get(str(rule.get("source_type") or ""), 0),
        -_specificity(rule),
        int(rule.get("serial_no") or 999999),
        str(rule_identity(rule) or ""),
    )


def select_group_representatives(rules, platform=""):
    """Return selected rules and stable supporting UIDs for one issue group."""
    rules = list(rules or [])
    requested_platform = str(platform or "").strip().lower()
    non_platform = [rule for rule in rules if not _platform_values(rule)]
    platform_rules = [rule for rule in rules if _platform_values(rule)]
    selected = []

    if non_platform:
        selected.append(sorted(non_platform, key=_selection_key)[0])

    if requested_platform:
        matching = [rule for rule in platform_rules if requested_platform in _platform_values(rule)]
        if matching:
            selected.append(sorted(matching, key=_selection_key)[0])

    selected_uids = {rule_identity(rule) for rule in selected}
    supporting = sorted(
        rule_identity(rule)
        for rule in rules
        if rule_identity(rule) and rule_identity(rule) not in selected_uids
    )
    return selected, supporting
