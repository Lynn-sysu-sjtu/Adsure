# -*- coding: utf-8 -*-
"""Compare keyword-only recall with keyword + semantic recall on test cases."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from field_mapper import map_feishu_payload
from kg_rule_store import load_rule_library
from rule_engine import build_context_package, recall_rules, validate_request


PROJECT_BASE = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_BASE / "test_cases" / "rule_engine_cases_v0.1.json"


def _load_cases(case_file=CASE_FILE):
    return json.loads(Path(case_file).read_text(encoding="utf-8"))


def _load_rules(base_dir):
    library = load_rule_library(base_dir)
    return library["data"].get("rules", [])


def _unique_ids(recalled):
    ids = []
    seen = set()
    for rule, _ in recalled:
        rule_id = rule.get("rule_id")
        if not rule_id or rule_id in seen:
            continue
        ids.append(rule_id)
        seen.add(rule_id)
    return ids


def _ordered_intersection(left_ids, right_ids):
    right = set(right_ids)
    return [rule_id for rule_id in left_ids if rule_id in right]


def _ordered_difference(left_ids, right_ids):
    right = set(right_ids)
    return [rule_id for rule_id in left_ids if rule_id not in right]


def compare_case(case, rules, fallback_supplement_threshold=None):
    request = map_feishu_payload(case["input_payload"])
    validate_request(request)
    context_package = build_context_package(request)

    keyword_recalled = recall_rules(rules, request, context_package=None)
    hybrid_recalled = recall_rules(
        rules,
        request,
        context_package=context_package,
        fallback_supplement_threshold=fallback_supplement_threshold,
    )

    keyword_rule_ids = _unique_ids(keyword_recalled)
    hybrid_rule_ids = _unique_ids(hybrid_recalled)
    semantic_extra_rule_ids = _ordered_difference(hybrid_rule_ids, keyword_rule_ids)
    expected_semantic_rule_ids = case.get("expected", {}).get("expected_semantic_rule_ids", [])

    semantic_expected_hit_ids = _ordered_intersection(semantic_extra_rule_ids, expected_semantic_rule_ids)
    semantic_missing_expected_ids = _ordered_difference(expected_semantic_rule_ids, semantic_extra_rule_ids)
    semantic_noise_rule_ids = _ordered_difference(semantic_extra_rule_ids, expected_semantic_rule_ids)

    return {
        "case_id": case.get("case_id"),
        "name": case.get("name"),
        "keyword_rule_ids": keyword_rule_ids,
        "hybrid_rule_ids": hybrid_rule_ids,
        "semantic_extra_rule_ids": semantic_extra_rule_ids,
        "expected_semantic_rule_ids": expected_semantic_rule_ids,
        "semantic_expected_hit_ids": semantic_expected_hit_ids,
        "semantic_missing_expected_ids": semantic_missing_expected_ids,
        "semantic_noise_rule_ids": semantic_noise_rule_ids,
        "semantic_gain_count": len(semantic_expected_hit_ids),
        "semantic_noise_count": len(semantic_noise_rule_ids),
    }


def compare_cases(base_dir=PROJECT_BASE, case_file=CASE_FILE, fallback_supplement_threshold=None):
    base = Path(base_dir)
    cases = _load_cases(case_file)
    rules = _load_rules(base)
    case_reports = [
        compare_case(case, rules, fallback_supplement_threshold=fallback_supplement_threshold)
        for case in cases
    ]
    rule_stats = _build_rule_stats(case_reports)

    return {
        "summary": {
            "case_count": len(case_reports),
            "semantic_case_count": sum(1 for item in case_reports if item["expected_semantic_rule_ids"]),
            "semantic_gain_count": sum(item["semantic_gain_count"] for item in case_reports),
            "semantic_noise_count": sum(item["semantic_noise_count"] for item in case_reports),
            "semantic_missing_expected_count": sum(
                len(item["semantic_missing_expected_ids"]) for item in case_reports
            ),
        },
        "rule_stats": rule_stats,
        "cases": case_reports,
    }


def _counted_items(counter):
    return [
        {"rule_id": rule_id, "count": count}
        for rule_id, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _build_rule_stats(case_reports):
    noise_counter = Counter()
    expected_hit_counter = Counter()
    noise_detail = defaultdict(list)

    for item in case_reports:
        case_id = item.get("case_id")
        for rule_id in item.get("semantic_noise_rule_ids", []):
            noise_counter[rule_id] += 1
            noise_detail[rule_id].append(case_id)
        for rule_id in item.get("semantic_expected_hit_ids", []):
            expected_hit_counter[rule_id] += 1

    return {
        "top_noise_rules": _counted_items(noise_counter),
        "top_expected_hit_rules": _counted_items(expected_hit_counter),
        "per_rule_noise_detail": dict(sorted(noise_detail.items())),
    }


def _fmt_ids(ids):
    return ", ".join(ids) if ids else "-"


def print_report(report):
    summary = report["summary"]
    print("Recall mode comparison")
    print("-" * 72)
    print(f"样例数: {summary['case_count']}")
    print(f"语义诊断样例数: {summary['semantic_case_count']}")
    print(f"召回提升数: {summary['semantic_gain_count']}")
    print(f"噪声数: {summary['semantic_noise_count']}")
    print(f"预期语义漏召回数: {summary['semantic_missing_expected_count']}")
    print("-" * 72)

    stats = report.get("rule_stats", {})
    print("Top noise rules")
    for item in stats.get("top_noise_rules", []):
        print(f"  {item['rule_id']}: {item['count']}")
    if not stats.get("top_noise_rules"):
        print("  -")
    print("Top expected hit rules")
    for item in stats.get("top_expected_hit_rules", []):
        print(f"  {item['rule_id']}: {item['count']}")
    if not stats.get("top_expected_hit_rules"):
        print("  -")
    print("Per-rule noise detail")
    for rule_id, case_ids in stats.get("per_rule_noise_detail", {}).items():
        print(f"  {rule_id}: {_fmt_ids(case_ids)}")
    if not stats.get("per_rule_noise_detail"):
        print("  -")
    print("-" * 72)

    for item in report["cases"]:
        print(f"[{item['case_id']}] {item['name']}")
        print(f"  keyword_only: {_fmt_ids(item['keyword_rule_ids'])}")
        print(f"  semantic_extra: {_fmt_ids(item['semantic_extra_rule_ids'])}")
        print(f"  expected_semantic: {_fmt_ids(item['expected_semantic_rule_ids'])}")
        print(f"  expected_hit: {_fmt_ids(item['semantic_expected_hit_ids'])}")
        print(f"  missing_expected: {_fmt_ids(item['semantic_missing_expected_ids'])}")
        print(f"  noise: {_fmt_ids(item['semantic_noise_rule_ids'])}")
        print(
            f"  gain={item['semantic_gain_count']} "
            f"noise={item['semantic_noise_count']}"
        )


def main():
    parser = argparse.ArgumentParser(description="Compare keyword-only and semantic recall modes.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    parser.add_argument("--fallback-supplement-threshold", type=float, default=None)
    args = parser.parse_args()

    report = compare_cases(fallback_supplement_threshold=args.fallback_supplement_threshold)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
