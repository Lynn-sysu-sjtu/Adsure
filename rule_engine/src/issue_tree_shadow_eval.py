# -*- coding: utf-8 -*-
"""Minimal deterministic metrics for issue-tree shadow recall reports."""

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _set(case, key):
    value = case.get(key) or []
    return {str(item) for item in value if str(item)}


def _p95(values):
    ordered = sorted(max(0, int(value or 0)) for value in values)
    if not ordered:
        return 0
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def evaluate_shadow_cases(cases):
    cases = list(cases or [])
    expected_issue_count = 0
    matched_issue_count = 0
    expected_rule_count = 0
    matched_rule_count = 0
    expected_rules = set()
    tree_rules = set()
    other_rules = set()
    invalid_paths = 0
    statuses = Counter()
    semantic_statuses = Counter()
    selection_statuses = Counter()
    latencies = []
    selected_expected_hits = 0
    selected_expected_count = 0
    selected_complete_case_hits = 0
    selected_positive_case_count = 0
    selected_rules = set()
    main_candidate_rules = set()
    role_promotion_violations = 0
    per_case_limit_violations = 0
    per_path_limit_violations = 0

    for case in cases:
        expected_issue_ids = _set(case, "expected_issue_ids")
        tree_issue_ids = _set(case, "tree_issue_ids")
        expected_rule_uids = _set(case, "expected_rule_uids")
        tree_rule_uids = _set(case, "tree_rule_uids")
        keyword_rule_uids = _set(case, "keyword_rule_uids")
        semantic_rule_uids = _set(case, "semantic_rule_uids")
        catalog_rule_uids = _set(case, "catalog_rule_uids")
        candidate_rule_uids = _set(case, "candidate_rule_uids")
        selected_direct_rule_uids = _set(case, "tree_selected_direct_rule_uids")
        selected_fact_check_rule_uids = _set(case, "tree_selected_fact_check_rule_uids")
        selected_actionable_rule_uids = _set(case, "tree_selected_actionable_rule_uids")
        non_actionable_rule_uids = _set(case, "tree_non_actionable_rule_uids")

        expected_issue_count += len(expected_issue_ids)
        matched_issue_count += len(expected_issue_ids & tree_issue_ids)
        expected_rule_count += len(expected_rule_uids)
        matched_rule_count += len(expected_rule_uids & tree_rule_uids)
        expected_rules.update(expected_rule_uids)
        tree_rules.update(tree_rule_uids)
        other_rules.update(keyword_rule_uids | semantic_rule_uids | catalog_rule_uids)
        selected_expected_hits += len(expected_rule_uids & selected_actionable_rule_uids)
        selected_expected_count += len(expected_rule_uids)
        if expected_rule_uids:
            selected_positive_case_count += 1
            selected_complete_case_hits += int(
                expected_rule_uids.issubset(selected_actionable_rule_uids)
            )
        selected_rules.update(selected_actionable_rule_uids)
        main_candidate_rules.update(
            candidate_rule_uids
            | keyword_rule_uids
            | semantic_rule_uids
            | catalog_rule_uids
        )
        selected_actionable_provenance = set()
        for ranking in case.get("tree_selection_path_rankings") or []:
            selected_in_path = set(ranking.get("per_path_selected_rule_uids") or [])
            selected_actionable_provenance.update(
                item.get("rule_uid")
                for item in ranking.get("ranked_rules") or []
                if item.get("rule_uid") in selected_in_path
                and item.get("mapping_role") in {"direct", "fact_check"}
            )
        role_promotion_violations += len(
            (selected_actionable_rule_uids & non_actionable_rule_uids)
            - selected_actionable_provenance
        )
        per_case_limit_violations += int(
            len(selected_actionable_rule_uids) > 8
            or len(selected_direct_rule_uids) > 6
            or len(selected_fact_check_rule_uids) > 2
        )
        for ranking in case.get("tree_selection_path_rankings") or []:
            per_path_limit_violations += int(
                len(ranking.get("per_path_selected_rule_uids") or []) > 3
            )
        invalid_paths += int(case.get("invalid_path_count") or 0)
        statuses[str(case.get("tree_status") or "unknown")] += 1
        semantic_statuses[str(case.get("tree_semantic_status") or "missing")] += 1
        selection_statuses[str(case.get("tree_selection_status") or "missing")] += 1
        latencies.append(case.get("latency_ms") or 0)

    return {
        "case_count": len(cases),
        "matched_expected_issue_count": matched_issue_count,
        "expected_issue_count": expected_issue_count,
        "issue_path_recall": (matched_issue_count / expected_issue_count) if expected_issue_count else None,
        "matched_expected_rule_count": matched_rule_count,
        "expected_rule_count": expected_rule_count,
        "rule_uid_recall": (matched_rule_count / expected_rule_count) if expected_rule_count else None,
        "tree_only_rule_uids": sorted(tree_rules - other_rules),
        "missed_by_tree_rule_uids": sorted(expected_rules - tree_rules),
        "shared_rule_uids": sorted(tree_rules & other_rules),
        "invalid_path_count": invalid_paths,
        "status_counts": dict(sorted(statuses.items())),
        "selected_actionable_expected_rule_hits": selected_expected_hits,
        "selected_actionable_expected_rule_count": selected_expected_count,
        "selected_actionable_rule_uid_recall": (
            selected_expected_hits / selected_expected_count
        ) if selected_expected_count else None,
        "selected_actionable_complete_case_hits": selected_complete_case_hits,
        "selected_actionable_positive_case_count": selected_positive_case_count,
        "selected_actionable_complete_case_recall": (
            selected_complete_case_hits / selected_positive_case_count
        ) if selected_positive_case_count else None,
        "selected_tree_only_rule_uids": sorted(selected_rules - main_candidate_rules),
        "semantic_status_counts": dict(sorted(semantic_statuses.items())),
        "selection_status_counts": dict(sorted(selection_statuses.items())),
        "role_promotion_violation_count": role_promotion_violations,
        "per_case_limit_violation_count": per_case_limit_violations,
        "per_path_limit_violation_count": per_path_limit_violations,
        "p95_latency_ms": _p95(latencies),
    }


def run_shadow_cases(cases, audit_fn, base_dir=None):
    records = []
    for case in cases:
        diagnostics = {}
        response = audit_fn(case["input_payload"], base_dir=base_dir, diagnostics=diagnostics)
        data = response.get("data") or {}
        shadow = data.get("issue_tree_shadow_recall") or {}
        matched = data.get("matched_rules") or []
        by_channel = {"keyword": set(), "semantic": set(), "llm_catalog": set()}
        for rule in matched:
            uid = rule.get("rule_uid")
            channel = rule.get("recall_channel")
            if uid and channel in by_channel:
                by_channel[channel].add(uid)
        expected = case.get("expected") or {}
        selection = shadow.get("rule_selection") or {}
        records.append({
            "case_id": case.get("case_id"),
            "response_code": response.get("code"),
            "expected_issue_ids": expected.get("expected_issue_ids") or [],
            "expected_rule_uids": expected.get("must_recall_rule_uids") or [],
            "keyword_rule_uids": sorted(by_channel["keyword"]),
            "semantic_rule_uids": sorted(by_channel["semantic"]),
            "catalog_rule_uids": sorted(by_channel["llm_catalog"]),
            "candidate_rule_uids": diagnostics.get("candidate_rule_uids") or [],
            "tree_issue_ids": [
                item.get("level_3_issue_id")
                for item in shadow.get("selected_issue_paths") or []
                if item.get("level_3_issue_id")
            ],
            "tree_rule_uids": shadow.get("eligible_rule_uids_after_gate") or [],
            "tree_expanded_rule_uids": shadow.get("eligible_rule_uids_after_gate") or [],
            "tree_selected_direct_rule_uids": selection.get("selected_direct_rule_uids") or [],
            "tree_selected_fact_check_rule_uids": selection.get("selected_fact_check_rule_uids") or [],
            "tree_selected_actionable_rule_uids": selection.get("selected_actionable_rule_uids") or [],
            "tree_non_actionable_rule_uids": selection.get("non_actionable_rule_uids") or [],
            "tree_rejected_paths": shadow.get("rejected_paths") or [],
            "tree_selection_dropped_rules": selection.get("dropped_rules") or [],
            "tree_selection_path_rankings": selection.get("path_rankings") or [],
            "tree_semantic_status": selection.get("semantic_status") or "missing",
            "tree_selection_status": selection.get("status") or "missing",
            "tree_status": shadow.get("status") or "missing",
            "invalid_path_count": len(shadow.get("rejected_paths") or []),
            "latency_ms": shadow.get("latency_ms") or 0,
        })
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate issue-tree shadow recall records.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--runtime-tree", default="")
    parser.add_argument("--backend", choices=("mock", "deepseek"), default="mock")
    parser.add_argument("--run-audits", action="store_true")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.cases).read_text(encoding="utf-8-sig"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if args.run_audits:
        import os
        from rule_engine import audit

        os.environ["ADSURE_ISSUE_TREE_SHADOW_ENABLED"] = "true"
        os.environ["ADSURE_ISSUE_TREE_BACKEND"] = args.backend
        os.environ.setdefault("ADSURE_LLM_BACKEND", "mock")
        records = run_shadow_cases(cases or [], audit, base_dir=args.base_dir)
    else:
        records = cases or []
        if records and "tree_status" not in records[0]:
            parser.error("Raw test cases require --run-audits; otherwise provide recorded shadow results.")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "runtime_tree": args.runtime_tree,
        "metrics": evaluate_shadow_cases(records),
        "cases": records,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    main()
