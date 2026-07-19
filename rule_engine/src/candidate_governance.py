# -*- coding: utf-8 -*-
"""Deterministic governance for the final DeepSeek candidate pool."""

import copy

from legal_issue_groups import (
    AUTHORITY_RANK,
    legal_issue_group_index,
    select_group_representatives,
)
from rule_identity import rule_identity


def merge_parent_candidates(recalled):
    merged = []
    by_identity = {}
    for rule, hits in recalled or []:
        identity = rule_identity(rule) or ("anonymous", id(rule))
        if identity not in by_identity:
            entry = [rule, list(dict.fromkeys(hits or []))]
            by_identity[identity] = entry
            merged.append(entry)
            continue
        existing = by_identity[identity][1]
        for hit in hits or []:
            if hit not in existing:
                existing.append(hit)
    return [(rule, hits) for rule, hits in merged]


def _requested_platform(request):
    context = request.get("context") or {}
    value = context.get("platforms") or context.get("platform") or ""
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def collapse_issue_groups(recalled, request, group_asset):
    index = legal_issue_group_index(group_asset or {"groups": []})
    grouped = {}
    output = []
    emitted_groups = set()

    for rule, hits in recalled:
        group = index.get(rule_identity(rule))
        if group is None:
            output.append((rule, hits))
            continue
        grouped.setdefault(group["issue_group_id"], []).append((rule, hits))

    for rule, hits in recalled:
        group = index.get(rule_identity(rule))
        if group is None:
            continue
        group_id = group["issue_group_id"]
        if group_id in emitted_groups:
            continue
        emitted_groups.add(group_id)
        members = grouped[group_id]
        member_rules = [item[0] for item in members]
        hits_by_uid = {rule_identity(item[0]): item[1] for item in members}
        selected, supporting = select_group_representatives(
            member_rules,
            platform=_requested_platform(request),
        )
        for position, selected_rule in enumerate(selected):
            selected_copy = copy.deepcopy(selected_rule)
            if position == 0 and supporting:
                selected_copy["supporting_rule_uids"] = supporting
            output.append((selected_copy, hits_by_uid.get(rule_identity(selected_rule), [])))
    return output


def _channels(hits):
    channels = set()
    for hit in hits or []:
        value = str(hit)
        if value.startswith("llm_catalog"):
            channels.add("catalog")
        elif value.startswith("semantic"):
            channels.add("semantic")
        elif value.startswith("regex:"):
            channels.add("regex")
        elif value.startswith("fact_") or value == "fact":
            channels.add("fact")
        else:
            channels.add("keyword")
    return channels


def candidate_sort_key(item):
    rule, hits = item
    channels = _channels(hits)
    source_rank = AUTHORITY_RANK.get(str(rule.get("source_type") or ""), 0)
    return (
        -len(channels),
        -("catalog" in channels),
        -("regex" in channels),
        -("keyword" in channels),
        -("semantic" in channels),
        -source_rank,
        rule.get("risk_level") != "高",
        int(rule.get("serial_no") or 999999),
        str(rule_identity(rule) or ""),
    )


def _is_fact(rule):
    return ((rule.get("recall") or {}).get("trigger_layer") or "content") == "fact"


def _is_platform(rule):
    return bool(rule.get("platform") or (rule.get("applies_to") or {}).get("platforms"))


def _is_open_content(rule):
    recall = rule.get("recall") or {}
    return (recall.get("trigger_layer") or "content") == "content" and bool(
        recall.get("catalog_recall_enabled")
    )


def apply_candidate_quotas(
    ranked,
    limit=8,
    max_fact=3,
    max_platform=2,
    reserve_open_content=1,
):
    selected = []
    selected_uids = set()
    fact_count = 0
    platform_count = 0

    def try_add(item):
        nonlocal fact_count, platform_count
        rule, _ = item
        uid = rule_identity(rule)
        if uid in selected_uids or len(selected) >= limit:
            return False
        if _is_fact(rule) and fact_count >= max_fact:
            return False
        if _is_platform(rule) and platform_count >= max_platform:
            return False
        selected.append(item)
        selected_uids.add(uid)
        fact_count += int(_is_fact(rule))
        platform_count += int(_is_platform(rule))
        return True

    if reserve_open_content:
        open_candidates = [item for item in ranked if _is_open_content(item[0])]
        if open_candidates:
            try_add(open_candidates[0])

    for item in ranked:
        try_add(item)
    return selected


def govern_candidates(recalled, request, group_asset, limit=8):
    merged = merge_parent_candidates(recalled)
    collapsed = collapse_issue_groups(merged, request or {}, group_asset or {"groups": []})
    ranked = sorted(collapsed, key=candidate_sort_key)
    return apply_candidate_quotas(ranked, limit=max(1, int(limit)))
