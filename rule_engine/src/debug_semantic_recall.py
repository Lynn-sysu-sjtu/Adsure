# -*- coding: utf-8 -*-
"""Debug semantic recall scores and filters for rule-engine cases."""

import argparse
import json
import os
from pathlib import Path

from field_mapper import map_feishu_payload
from kg_rule_store import load_rule_library
from rule_engine import build_context_package, recall_rules
from semantic_recall import semantic_recall_diagnostics, semantic_recall_rules


PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_CASES_PATH = PROJECT_BASE / "test_cases" / "rule_engine_cases_v0.1.json"


def _load_cases(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _selected_cases(cases, case_ids, case_prefix):
    if case_ids:
        wanted = set(case_ids)
        return [case for case in cases if case.get("case_id") in wanted]
    return [case for case in cases if str(case.get("case_id", "")).startswith(case_prefix)]


def _rule_ids(recalled):
    return [rule.get("rule_id") for rule, _ in recalled]


def _semantic_pool(rules, keyword_recalled):
    if not keyword_recalled:
        return rules
    primary_rules = [
        rule
        for rule in rules
        if (rule.get("recall", {}) or {}).get("semantic_role") == "primary"
    ]
    return primary_rules or []


def _print_case(case, rules, args):
    request = map_feishu_payload(case["input_payload"])
    context_package = build_context_package(request)
    keyword_recalled = recall_rules(rules, request, context_package=None)
    pool = _semantic_pool(rules, keyword_recalled)
    diagnostics = semantic_recall_diagnostics(
        pool,
        request,
        context_package,
        threshold=args.threshold,
        backend=args.backend,
        vector_index_path=args.vector_index,
        top_k=args.top_k,
    )
    semantic_recalled = semantic_recall_rules(
        pool,
        request,
        context_package,
        threshold=args.threshold,
        limit=args.limit,
        backend=args.backend,
        vector_index_path=args.vector_index,
    )

    expected = case.get("expected", {})
    print("=" * 88)
    print(f"case_id: {case.get('case_id')} | {case.get('name')}")
    print(f"expected_semantic_rule_ids: {expected.get('expected_semantic_rule_ids', [])}")
    print(f"keyword_rule_ids: {_rule_ids(keyword_recalled)}")
    print(f"semantic_matched_rule_ids: {_rule_ids(semantic_recalled)}")
    print(f"backend: {diagnostics['backend']} | threshold: {diagnostics['threshold']} | applicable: {diagnostics['applicable_count']} | rejected: {diagnostics['rejected_count']}")
    print(f"query: {diagnostics['query'][:240]}")
    print("top_candidates:")
    for item in diagnostics["top_candidates"]:
        passed = "PASS" if item["passed_threshold"] else "MISS"
        print(
            f"  {passed} score={item['score']:.6f} "
            f"rule_id={item['rule_id']} serial_no={item.get('serial_no')} title={item.get('title')}"
        )
    if args.show_rejected:
        print("rejected_rules:")
        for item in diagnostics["rejected_rules"][: args.rejected_limit]:
            print(f"  rule_id={item.get('rule_id')} reasons={','.join(item.get('reasons', []))}")


def main():
    parser = argparse.ArgumentParser(description="Debug semantic recall top scores and filters.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--base-dir", default=str(PROJECT_BASE))
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--case-prefix", default="CASE-SEM")
    parser.add_argument("--backend", default=os.getenv("ADSURE_SEMANTIC_BACKEND") or "zhipu")
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--vector-index", default=os.getenv("ADSURE_RULE_VECTOR_INDEX"))
    parser.add_argument("--show-rejected", action="store_true")
    parser.add_argument("--rejected-limit", type=int, default=30)
    args = parser.parse_args()

    library = load_rule_library(Path(args.base_dir))
    rules = library["data"].get("rules", [])
    cases = _selected_cases(_load_cases(args.cases), args.case_id, args.case_prefix)
    if not cases:
        raise SystemExit("No matching cases.")
    for case in cases:
        _print_case(case, rules, args)


if __name__ == "__main__":
    main()
