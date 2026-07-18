# -*- coding: utf-8 -*-
"""Diagnose semantic recall candidates for selected baseline cases.

This script is read-only for jsonbase/vectorbase. It reports the top semantic
candidates before and after the rule engine's current strategy gate so semantic
recall tuning can be evidence-based.
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from field_mapper import map_feishu_payload
from kg_rule_store import load_rule_library
from rule_engine import build_context_package, recall_rules
from semantic_recall import semantic_recall_diagnostics


PROJECT_BASE = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_BASE / "test_cases" / "rule_engine_cases_v0.1.json"
REPORT_DIR = PROJECT_BASE / "reports" / "semantic_recall_diagnostics"
DEFAULT_CASE_IDS = [
    "CASE-SEM-001",
    "CASE-SEM-002",
    "CASE-SEM-003",
    "CASE-SEM-004",
    "CASE-SEM-005",
]


def _load_cases(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rule_id_set(items):
    return {rule.get("rule_id") for rule, _ in items if rule.get("rule_id")}


def _content_rules(rules):
    result = []
    for rule in rules:
        recall = rule.get("recall", {}) or {}
        if (recall.get("trigger_layer") or "content") == "content":
            result.append(rule)
    return result


def _primary_rules(rules):
    return [rule for rule in rules if (rule.get("recall", {}) or {}).get("semantic_role") == "primary"]


def _expected_candidate_stats(candidates, expected_ids):
    by_id = {item.get("rule_id"): item for item in candidates}
    stats = []
    for rule_id in expected_ids:
        item = by_id.get(rule_id)
        stats.append(
            {
                "rule_id": rule_id,
                "present_in_top_candidates": bool(item),
                "rank": item.get("rank") if item else None,
                "score": item.get("score") if item else None,
                "passed_threshold": item.get("passed_threshold") if item else False,
                "semantic_role": item.get("semantic_role") if item else None,
                "trigger_layer": item.get("trigger_layer") if item else None,
            }
        )
    return stats


def _diagnose_case(case, rules, args):
    request = map_feishu_payload(case["input_payload"])
    context_package = build_context_package(request)
    content_rules = _content_rules(rules)
    keyword_recalled = recall_rules(
        content_rules,
        request,
        context_package=None,
        keyword_limit=args.keyword_limit,
        semantic_limit=args.semantic_limit,
    )
    keyword_ids = sorted(_rule_id_set(keyword_recalled))
    expected = case.get("expected", {}) or {}
    expected_semantic_ids = expected.get("expected_semantic_rule_ids", []) or []

    all_diag = semantic_recall_diagnostics(
        content_rules,
        request,
        context_package,
        threshold=args.threshold,
        backend=args.backend,
        top_k=args.top_k,
    )

    if keyword_recalled:
        strategy_pool = _primary_rules(content_rules)
        strategy_gate = "keyword_hit_primary_only"
    else:
        strategy_pool = content_rules
        strategy_gate = "no_keyword_all_content_semantic_rules"

    strategy_diag = semantic_recall_diagnostics(
        strategy_pool,
        request,
        context_package,
        threshold=args.threshold,
        backend=args.backend,
        top_k=args.top_k,
    )

    expected_stats = _expected_candidate_stats(all_diag["top_candidates"], expected_semantic_ids)
    blocked_expected = [
        item
        for item in expected_stats
        if item.get("present_in_top_candidates")
        and keyword_recalled
        and item.get("semantic_role") != "primary"
    ]

    return {
        "case_id": case.get("case_id"),
        "name": case.get("name"),
        "query": all_diag.get("query"),
        "expected_semantic_rule_ids": expected_semantic_ids,
        "keyword_recalled_rule_ids": keyword_ids,
        "strategy_gate": strategy_gate,
        "blocked_expected_by_current_strategy": blocked_expected,
        "expected_candidate_stats": expected_stats,
        "all_content_semantic": {
            "backend": all_diag.get("backend"),
            "threshold": all_diag.get("threshold"),
            "applicable_count": all_diag.get("applicable_count"),
            "rejected_count": all_diag.get("rejected_count"),
            "top_candidates": all_diag.get("top_candidates", []),
        },
        "current_strategy_semantic": {
            "backend": strategy_diag.get("backend"),
            "threshold": strategy_diag.get("threshold"),
            "applicable_count": strategy_diag.get("applicable_count"),
            "rejected_count": strategy_diag.get("rejected_count"),
            "top_candidates": strategy_diag.get("top_candidates", []),
        },
    }


def build_report(args):
    library = load_rule_library(args.base_dir)
    rules = library["data"].get("rules", [])
    selected_ids = set(args.case_ids)
    cases = [case for case in _load_cases(args.case_file) if case.get("case_id") in selected_ids]
    case_reports = [_diagnose_case(case, rules, args) for case in cases]
    return {
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "config": {
            "base_dir": str(Path(args.base_dir).resolve()),
            "case_file": str(Path(args.case_file).resolve()),
            "backend": args.backend,
            "threshold": args.threshold,
            "top_k": args.top_k,
            "case_ids": args.case_ids,
            "ADSURE_RULE_VECTOR_INDEX": os.getenv("ADSURE_RULE_VECTOR_INDEX", ""),
            "ADSURE_SEMANTIC_THRESHOLD": os.getenv("ADSURE_SEMANTIC_THRESHOLD", ""),
        },
        "summary": {
            "case_count": len(case_reports),
            "cases_with_keyword_recall": sum(1 for item in case_reports if item["keyword_recalled_rule_ids"]),
            "expected_in_top_candidates_count": sum(
                1
                for item in case_reports
                if all(stat["present_in_top_candidates"] for stat in item["expected_candidate_stats"])
            ),
            "blocked_expected_by_current_strategy_count": sum(
                1 for item in case_reports if item["blocked_expected_by_current_strategy"]
            ),
        },
        "cases": case_reports,
    }


def save_report(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report['timestamp']}_semantic_recall_case_diagnostics.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def print_summary(report, path=None):
    summary = report["summary"]
    print("Semantic recall diagnostics")
    print("-" * 72)
    print(f"backend: {report['config']['backend']}")
    print(f"threshold: {report['config']['threshold']}")
    print(f"cases: {summary['case_count']}")
    print(f"cases_with_keyword_recall: {summary['cases_with_keyword_recall']}")
    print(f"expected_in_top_candidates_count: {summary['expected_in_top_candidates_count']}")
    print(f"blocked_expected_by_current_strategy_count: {summary['blocked_expected_by_current_strategy_count']}")
    if path:
        print(f"report: {path}")
    print("-" * 72)
    for item in report["cases"]:
        top = item["all_content_semantic"]["top_candidates"][:5]
        compact_top = [
            f"{candidate.get('rank')}:{candidate.get('rule_id')}:{candidate.get('score')}:{candidate.get('semantic_role')}"
            for candidate in top
        ]
        print(f"{item['case_id']} keyword={item['keyword_recalled_rule_ids']} gate={item['strategy_gate']}")
        print(f"  expected={item['expected_semantic_rule_ids']}")
        print(f"  expected_stats={item['expected_candidate_stats']}")
        print(f"  top5={compact_top}")
        if item["blocked_expected_by_current_strategy"]:
            print(f"  blocked_expected={item['blocked_expected_by_current_strategy']}")


def main():
    parser = argparse.ArgumentParser(description="Diagnose top semantic recall candidates for selected cases.")
    parser.add_argument("--base-dir", default=str(PROJECT_BASE))
    parser.add_argument("--case-file", default=str(CASE_FILE))
    parser.add_argument("--output-dir", default=str(REPORT_DIR))
    parser.add_argument("--case-ids", nargs="+", default=DEFAULT_CASE_IDS)
    parser.add_argument("--backend", default=os.getenv("ADSURE_SEMANTIC_BACKEND", "zhipu"))
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--keyword-limit", type=int, default=8)
    parser.add_argument("--semantic-limit", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    report = build_report(args)
    path = None if args.no_save else save_report(report, args.output_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_summary(report, path=path)


if __name__ == "__main__":
    main()