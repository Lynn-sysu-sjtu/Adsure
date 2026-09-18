# -*- coding: utf-8 -*-
"""Deterministically expand approved issue paths into role-separated rule UIDs."""

from issue_tree_runtime import _rule_rejection_reason


ROLE_OUTPUT_KEYS = {
    "direct": "direct_rule_uids",
    "fact_check": "fact_check_rule_uids",
    "proactive_check": "proactive_check_rule_uids",
    "supporting_basis": "supporting_rule_uids",
    "exception": "exception_rule_uids",
}


def _redirect_target(uid, redirects):
    seen = set()
    current = uid
    while current in redirects and current not in seen:
        seen.add(current)
        current = redirects[current]
    return current


def expand_issue_paths(issue_ids, mapping_asset, rules_by_uid, request, uid_redirects=None):
    selected = set(issue_ids or [])
    redirects = dict(uid_redirects or {})
    result = {key: [] for key in ROLE_OUTPUT_KEYS.values()}
    result.update(
        {
            "mapped_rule_uids_before_gate": [],
            "eligible_rule_uids_after_gate": [],
            "rejected_rule_uids": [],
            "trace": [],
        }
    )
    trace_by_key = {}

    for mapping in mapping_asset.get("mappings") or []:
        issue_id = str(mapping.get("issue_id") or "").strip()
        if issue_id not in selected:
            continue
        original_uid = str(mapping.get("rule_uid") or "").strip()
        role = str(mapping.get("mapping_type") or "").strip()
        canonical_uid = _redirect_target(original_uid, redirects)
        if original_uid:
            result["mapped_rule_uids_before_gate"].append(original_uid)
        if role not in ROLE_OUTPUT_KEYS:
            result["rejected_rule_uids"].append(
                {"rule_uid": original_uid, "canonical_rule_uid": canonical_uid, "issue_id": issue_id, "reason": "unsupported_mapping_role"}
            )
            continue
        rule = rules_by_uid.get(canonical_uid)
        reason = "missing_rule_uid" if not rule else _rule_rejection_reason(rule, request, role)
        if reason:
            result["rejected_rule_uids"].append(
                {"rule_uid": original_uid, "canonical_rule_uid": canonical_uid, "issue_id": issue_id, "reason": reason}
            )
            continue

        result[ROLE_OUTPUT_KEYS[role]].append(canonical_uid)
        result["eligible_rule_uids_after_gate"].append(canonical_uid)
        trace_key = (canonical_uid, issue_id, role)
        trace = trace_by_key.setdefault(
            trace_key,
            {
                "canonical_rule_uid": canonical_uid,
                "original_rule_uids": [],
                "issue_id": issue_id,
                "mapping_type": role,
            },
        )
        trace["original_rule_uids"].append(original_uid)

    for key in list(ROLE_OUTPUT_KEYS.values()) + [
        "mapped_rule_uids_before_gate",
        "eligible_rule_uids_after_gate",
    ]:
        result[key] = sorted(set(result[key]))
    for trace in trace_by_key.values():
        trace["original_rule_uids"] = sorted(set(trace["original_rule_uids"]))
    result["trace"] = sorted(
        trace_by_key.values(),
        key=lambda item: (item["canonical_rule_uid"], item["issue_id"], item["mapping_type"]),
    )
    result["rejected_rule_uids"] = sorted(
        result["rejected_rule_uids"],
        key=lambda item: (str(item.get("rule_uid")), str(item.get("issue_id")), str(item.get("reason"))),
    )
    return result
