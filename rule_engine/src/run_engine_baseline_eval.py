# -*- coding: utf-8 -*-
"""Run baseline evaluation for the rule engine and persist metric reports.

This script is intentionally different from run_rule_engine_cases.py:
- core audit metrics exclude routing, because routing is a business workflow
  strategy still under discussion;
- LLM behavior is measured separately, including JSON validity, candidate-rule
  citation, hallucinated rule ids, and outside-rule risk count;
- reports are saved for comparison across mock/deepseek/zhipu baselines.
"""

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from audit_api import audit_endpoint


PROJECT_BASE = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_BASE / "test_cases" / "rule_engine_cases_v0.1.json"
REPORT_DIR = PROJECT_BASE / "test_reports"

DIMENSION_KEYS = ["审核_推荐违规类型", "瀹℃牳_鎺ㄨ崘杩濊绫诲瀷"]
RISK_KEYS = ["审核_推荐风险等级", "瀹℃牳_鎺ㄨ崘椋庨櫓绛夌骇"]


def _load_cases(case_file=CASE_FILE):
    return json.loads(Path(case_file).read_text(encoding="utf-8"))


def filter_cases_by_layer(cases, layers=None):
    selected_layers = set(layers or {"content"})
    if "all" in selected_layers:
        return list(cases)
    return [case for case in cases if (case.get("case_layer") or "content") in selected_layers]

def _first_value(data, keys, default=None):
    for key in keys:
        if key in data:
            return data[key]
    return default


def _as_set(value):
    if value is None:
        return set()
    if isinstance(value, list):
        return {item for item in value if item}
    return {value}


def _case_rate(numerator, denominator):
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def _rule_ids_from_judgments(llm_judgment):
    ids = []
    for item in llm_judgment.get("rule_judgments", []) or []:
        rule_id = item.get("rule_id")
        if rule_id:
            ids.append(rule_id)
    raw = llm_judgment.get("raw_response", {}) or {}
    for item in raw.get("matched_rules", []) or []:
        rule_id = item.get("rule_id")
        if rule_id:
            ids.append(rule_id)
    return sorted(set(ids))


def _outside_rule_risks(llm_judgment):
    risks = llm_judgment.get("outside_rule_risks")
    if risks is None:
        risks = (llm_judgment.get("raw_response", {}) or {}).get("outside_rule_risks", [])
    if isinstance(risks, list):
        return risks
    if risks:
        return [risks]
    return []


def _safe_filename(name):
    return re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("_") or "baseline"


def _rule_detail(rule):
    recall = rule.get("recall") or {}
    legal_attention = rule.get("legal_attention") or {}
    return {
        "rule_id": rule.get("rule_id"),
        "rule_uid": rule.get("rule_uid"),
        "title": rule.get("title"),
        "trigger_layer": recall.get("trigger_layer") or rule.get("trigger_layer"),
        "legal_attention_default_route": legal_attention.get("default_route"),
        "risk_level": rule.get("risk_level"),
        "recall_channel": rule.get("recall_channel"),
    }


def _format_rule_detail(rule):
    pieces = [
        rule.get("rule_id") or "<no-rule-id>",
        rule.get("rule_uid") or "<no-rule-uid>",
        rule.get("trigger_layer") or "<no-layer>",
        rule.get("legal_attention_default_route") or "<no-la-route>",
        rule.get("risk_level") or "<no-risk>",
        rule.get("recall_channel") or "<no-channel>",
        rule.get("title") or "<no-title>",
    ]
    return " | ".join(str(item) for item in pieces)

def evaluate_response(case, response, elapsed_ms=0):
    expected = case.get("expected", {})
    response_ok = response.get("code") == 0

    base_report = {
        "case_id": case.get("case_id"),
        "name": case.get("name"),
        "elapsed_ms": elapsed_ms,
        "checks": {
            "response_ok": response_ok,
            "recall_ok": False,
            "semantic_expected_ok": True,
            "dimension_ok": False,
            "risk_ok": False,
            "rule_engine_risk_ok": False,
            "llm_risk_ok": False,
            "final_risk_ok": False,
            "routing_ok": False,
            "core_audit_ok": False,
        },
        "expected": {
            "must_recall_rule_ids": expected.get("must_recall_rule_ids", []),
            "expected_semantic_rule_ids": expected.get("expected_semantic_rule_ids", []),
            "expected_dimensions": expected.get("expected_dimensions", []),
            "expected_risk_level": expected.get("expected_risk_level"),
            "expected_routing": expected.get("expected_routing"),
        },
        "actual": {},
        "risk_assessment": {},
        "semantic": {},
        "llm_checks": {
            "json_valid": False,
            "rule_citation_ok": False,
            "cited_rule_ids": [],
            "hallucinated_rule_ids": [],
            "outside_rule_risk_count": 0,
            "outside_rule_risks": [],
        },
        "error": None,
    }

    if not response_ok:
        base_report["error"] = response.get("msg") or "audit_endpoint returned non-zero code"
        return base_report

    data = response.get("data", {})
    matched_rules = data.get("matched_rules", []) or []
    matched_rule_details = [_rule_detail(rule) for rule in matched_rules]
    matched_ids = sorted({rule.get("rule_id") for rule in matched_rules if rule.get("rule_id")})
    matched_id_set = set(matched_ids)
    semantic_matched_ids = sorted(
        {
            rule.get("rule_id")
            for rule in matched_rules
            if rule.get("rule_id") and rule.get("recall_channel") == "semantic"
        }
    )
    actual_dimensions = sorted(_as_set(_first_value(data, DIMENSION_KEYS, [])))
    actual_risk = _first_value(data, RISK_KEYS)
    risk_assessment = data.get("risk_assessment", {}) or {}
    rule_engine_risk = risk_assessment.get("rule_engine_risk_level") or actual_risk
    llm_risk = risk_assessment.get("llm_risk_level") or (data.get("llm_judgment", {}) or {}).get("overall_risk_level") or actual_risk
    final_risk = risk_assessment.get("final_risk_level") or actual_risk
    actual_routing = data.get("routing")

    required_ids = set(expected.get("must_recall_rule_ids", []))
    expected_semantic_ids = set(expected.get("expected_semantic_rule_ids", []))
    expected_dimensions = set(expected.get("expected_dimensions", []))

    recall_ok = required_ids.issubset(matched_id_set)
    semantic_expected_ok = expected_semantic_ids.issubset(set(semantic_matched_ids))
    dimension_ok = expected_dimensions.issubset(set(actual_dimensions))
    expected_risk = expected.get("expected_risk_level")
    rule_engine_risk_ok = rule_engine_risk == expected_risk
    llm_risk_ok = llm_risk == expected_risk
    final_risk_ok = final_risk == expected_risk
    risk_ok = final_risk_ok
    routing_ok = actual_routing == expected.get("expected_routing")
    core_audit_ok = response_ok and recall_ok and semantic_expected_ok and dimension_ok and final_risk_ok

    llm_judgment = data.get("llm_judgment", {}) or {}
    json_valid = isinstance(llm_judgment, dict) and not llm_judgment.get("parse_error")
    cited_rule_ids = _rule_ids_from_judgments(llm_judgment)
    hallucinated_rule_ids = sorted(set(cited_rule_ids) - matched_id_set)
    if matched_ids:
        rule_citation_ok = bool(set(cited_rule_ids) & matched_id_set) and not hallucinated_rule_ids
    else:
        rule_citation_ok = not cited_rule_ids
    outside_risks = _outside_rule_risks(llm_judgment)

    base_report["checks"] = {
        "response_ok": response_ok,
        "recall_ok": recall_ok,
        "semantic_expected_ok": semantic_expected_ok,
        "dimension_ok": dimension_ok,
        "risk_ok": risk_ok,
        "rule_engine_risk_ok": rule_engine_risk_ok,
        "llm_risk_ok": llm_risk_ok,
        "final_risk_ok": final_risk_ok,
        "routing_ok": routing_ok,
        "core_audit_ok": core_audit_ok,
    }
    base_report["actual"] = {
        "matched_rule_ids": matched_ids,
        "matched_rule_details": matched_rule_details,
        "dimensions": actual_dimensions,
        "risk_level": final_risk,
        "rule_engine_risk_level": rule_engine_risk,
        "llm_risk_level": llm_risk,
        "final_risk_level": final_risk,
        "routing": actual_routing,
        "llm_engine": llm_judgment.get("engine"),
        "llm_mode": llm_judgment.get("mode"),
    }
    base_report["risk_assessment"] = {
        "rule_engine_risk_level": rule_engine_risk,
        "llm_risk_level": llm_risk,
        "final_risk_level": final_risk,
        "risk_disagreement": risk_assessment.get("risk_disagreement", rule_engine_risk != llm_risk),
        "risk_disagreement_reason": risk_assessment.get("risk_disagreement_reason"),
        "final_risk_source": risk_assessment.get("final_risk_source", "legacy_single_risk"),
        "final_risk_reason": risk_assessment.get("final_risk_reason"),
    }
    base_report["semantic"] = {
        "semantic_matched_rule_ids": semantic_matched_ids,
        "expected_semantic_rule_ids": sorted(expected_semantic_ids),
        "semantic_missing_expected_rule_ids": sorted(expected_semantic_ids - set(semantic_matched_ids)),
    }
    base_report["llm_checks"] = {
        "json_valid": json_valid,
        "rule_citation_ok": rule_citation_ok,
        "cited_rule_ids": cited_rule_ids,
        "hallucinated_rule_ids": hallucinated_rule_ids,
        "outside_rule_risk_count": len(outside_risks),
        "outside_rule_risks": outside_risks,
    }
    return base_report


def evaluate_case(case, base_dir=PROJECT_BASE):
    start = time.perf_counter()
    response = audit_endpoint(case["input_payload"], base_dir=base_dir)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    return evaluate_response(case, response, elapsed_ms=elapsed_ms)


def summarize_case_reports(case_reports):
    case_count = len(case_reports)
    response_ok_count = sum(1 for item in case_reports if item["checks"].get("response_ok"))
    core_ok_count = sum(1 for item in case_reports if item["checks"].get("core_audit_ok"))
    recall_ok_count = sum(1 for item in case_reports if item["checks"].get("recall_ok"))
    semantic_ok_count = sum(1 for item in case_reports if item["checks"].get("semantic_expected_ok", True))
    dimension_ok_count = sum(1 for item in case_reports if item["checks"].get("dimension_ok"))
    risk_ok_count = sum(1 for item in case_reports if item["checks"].get("risk_ok"))
    rule_engine_risk_ok_count = sum(1 for item in case_reports if item["checks"].get("rule_engine_risk_ok"))
    llm_risk_ok_count = sum(1 for item in case_reports if item["checks"].get("llm_risk_ok"))
    final_risk_ok_count = sum(1 for item in case_reports if item["checks"].get("final_risk_ok"))
    risk_disagreement_count = sum(1 for item in case_reports if item.get("risk_assessment", {}).get("risk_disagreement"))
    routing_ok_count = sum(1 for item in case_reports if item["checks"].get("routing_ok"))
    llm_json_valid_count = sum(1 for item in case_reports if item.get("llm_checks", {}).get("json_valid"))
    llm_rule_citation_ok_count = sum(1 for item in case_reports if item.get("llm_checks", {}).get("rule_citation_ok"))
    hallucination_case_count = sum(1 for item in case_reports if item.get("llm_checks", {}).get("hallucinated_rule_ids"))
    outside_rule_risk_count = sum(item.get("llm_checks", {}).get("outside_rule_risk_count", 0) for item in case_reports)
    semantic_matched_case_count = sum(
        1 for item in case_reports if item.get("semantic", {}).get("semantic_matched_rule_ids", [])
    )
    error_count = sum(1 for item in case_reports if item.get("error"))
    total_elapsed = sum(item.get("elapsed_ms", 0) for item in case_reports)

    return {
        "case_count": case_count,
        "response_ok_count": response_ok_count,
        "error_count": error_count,
        "core_audit_pass_count": core_ok_count,
        "core_audit_fail_count": case_count - core_ok_count,
        "core_audit_pass_rate": _case_rate(core_ok_count, case_count),
        "recall_pass_count": recall_ok_count,
        "recall_pass_rate": _case_rate(recall_ok_count, case_count),
        "semantic_expected_pass_count": semantic_ok_count,
        "semantic_expected_pass_rate": _case_rate(semantic_ok_count, case_count),
        "dimension_pass_count": dimension_ok_count,
        "dimension_pass_rate": _case_rate(dimension_ok_count, case_count),
        "risk_level_match_count": risk_ok_count,
        "risk_level_match_rate": _case_rate(risk_ok_count, case_count),
        "rule_engine_risk_match_count": rule_engine_risk_ok_count,
        "rule_engine_risk_match_rate": _case_rate(rule_engine_risk_ok_count, case_count),
        "llm_risk_match_count": llm_risk_ok_count,
        "llm_risk_match_rate": _case_rate(llm_risk_ok_count, case_count),
        "final_risk_match_count": final_risk_ok_count,
        "final_risk_match_rate": _case_rate(final_risk_ok_count, case_count),
        "risk_disagreement_count": risk_disagreement_count,
        "routing_pass_count": routing_ok_count,
        "routing_pass_rate": _case_rate(routing_ok_count, case_count),
        "semantic_matched_case_count": semantic_matched_case_count,
        "llm_json_valid_count": llm_json_valid_count,
        "llm_json_valid_rate": _case_rate(llm_json_valid_count, case_count),
        "llm_rule_citation_ok_count": llm_rule_citation_ok_count,
        "llm_rule_citation_rate": _case_rate(llm_rule_citation_ok_count, case_count),
        "llm_hallucination_case_count": hallucination_case_count,
        "outside_rule_risk_count": outside_rule_risk_count,
        "average_elapsed_ms": round(total_elapsed / case_count, 2) if case_count else 0.0,
    }


def build_report(cases, baseline_name, case_layers=None):
    selected_cases = filter_cases_by_layer(cases, case_layers)
    case_reports = [evaluate_case(case) for case in selected_cases]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return {
        "baseline_name": baseline_name,
        "timestamp": timestamp,
        "case_layers": sorted(set(case_layers or {"content"})),
        "config": {
            "ADSURE_LLM_BACKEND": os.getenv("ADSURE_LLM_BACKEND", "mock"),
            "ADSURE_LLM_MODE": os.getenv("ADSURE_LLM_MODE", "strict"),
            "ADSURE_SEMANTIC_BACKEND": os.getenv("ADSURE_SEMANTIC_BACKEND", "local"),
            "DEEPSEEK_MODEL": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "ZHIPU_EMBEDDING_MODEL": os.getenv("ZHIPU_EMBEDDING_MODEL", "embedding-3"),
        },
        "summary": summarize_case_reports(case_reports),
        "cases": case_reports,
    }


def save_report(report, output_dir=REPORT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{report['timestamp']}_{_safe_filename(report['baseline_name'])}.json"
    path = output_dir / filename
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def print_summary(report, report_path=None):
    summary = report["summary"]
    print("Engine baseline evaluation")
    print("-" * 72)
    print(f"baseline: {report['baseline_name']}")
    print(f"config: {json.dumps(report['config'], ensure_ascii=False)}")
    print(f"case_layers: {report.get('case_layers', ['content'])}")
    print(f"cases: {summary['case_count']}")
    print(f"error_count: {summary.get('error_count', 0)}")
    print(f"core_audit_pass_rate: {summary['core_audit_pass_rate']} ({summary['core_audit_pass_count']}/{summary['case_count']})")
    print(f"recall_pass_rate: {summary['recall_pass_rate']} ({summary['recall_pass_count']}/{summary['case_count']})")
    print(f"dimension_pass_rate: {summary['dimension_pass_rate']} ({summary['dimension_pass_count']}/{summary['case_count']})")
    print(f"risk_level_match_rate: {summary['risk_level_match_rate']} ({summary['risk_level_match_count']}/{summary['case_count']})")
    print(f"rule_engine_risk_match_rate: {summary['rule_engine_risk_match_rate']} ({summary['rule_engine_risk_match_count']}/{summary['case_count']})")
    print(f"llm_risk_match_rate: {summary['llm_risk_match_rate']} ({summary['llm_risk_match_count']}/{summary['case_count']})")
    print(f"final_risk_match_rate: {summary['final_risk_match_rate']} ({summary['final_risk_match_count']}/{summary['case_count']})")
    print(f"risk_disagreement_count: {summary['risk_disagreement_count']}")
    print(f"routing_pass_rate: {summary['routing_pass_rate']} ({summary['routing_pass_count']}/{summary['case_count']})")
    print(f"llm_json_valid_rate: {summary['llm_json_valid_rate']} ({summary['llm_json_valid_count']}/{summary['case_count']})")
    print(f"llm_rule_citation_rate: {summary['llm_rule_citation_rate']} ({summary['llm_rule_citation_ok_count']}/{summary['case_count']})")
    print(f"llm_hallucination_case_count: {summary['llm_hallucination_case_count']}")
    print(f"outside_rule_risk_count: {summary['outside_rule_risk_count']}")
    print(f"semantic_matched_case_count: {summary['semantic_matched_case_count']}")
    print(f"average_elapsed_ms: {summary['average_elapsed_ms']}")
    if report_path:
        print(f"report: {report_path}")

    error_cases = [item for item in report["cases"] if item.get("error")]
    core_failures = [item for item in report["cases"] if not item["checks"].get("core_audit_ok")]
    routing_failures = [item for item in report["cases"] if not item["checks"].get("routing_ok")]
    if error_cases:
        print("-" * 72)
        print("Engine/API errors")
        for item in error_cases:
            print(f"  {item['case_id']}: {item.get('error')}")
    if core_failures:
        print("-" * 72)
        print("Core audit failures")
        for item in core_failures:
            risk = item.get("risk_assessment", {})
            print(
                f"  {item['case_id']}: recall={item['checks']['recall_ok']} "
                f"dimension={item['checks']['dimension_ok']} "
                f"final_risk={item['checks']['final_risk_ok']} "
                f"rule={risk.get('rule_engine_risk_level')} "
                f"llm={risk.get('llm_risk_level')} "
                f"final={risk.get('final_risk_level')}"
            )
            for rule in item.get("actual", {}).get("matched_rule_details", [])[:12]:
                print(f"    - {_format_rule_detail(rule)}")
    if routing_failures:
        print("-" * 72)
        print("Routing failures (not counted in core audit)")
        for item in routing_failures:
            print(f"  {item['case_id']}: actual={item['actual'].get('routing')} expected={item['expected'].get('expected_routing')}")
            for rule in item.get("actual", {}).get("matched_rule_details", [])[:12]:
                print(f"    - {_format_rule_detail(rule)}")


def _default_baseline_name():
    return "_".join(
        [
            os.getenv("ADSURE_LLM_BACKEND", "mock"),
            os.getenv("ADSURE_LLM_MODE", "strict"),
            os.getenv("ADSURE_SEMANTIC_BACKEND", "local"),
        ]
    )


def main():
    parser = argparse.ArgumentParser(description="Run rule-engine baseline evaluation and save metrics.")
    parser.add_argument("--baseline-name", default=_default_baseline_name())
    parser.add_argument("--case-file", default=str(CASE_FILE))
    parser.add_argument("--output-dir", default=str(REPORT_DIR))
    parser.add_argument("--json", action="store_true", help="Print full report JSON.")
    parser.add_argument("--no-save", action="store_true", help="Do not save report to disk.")
    parser.add_argument("--case-layer", action="append", default=None, choices=["content", "workflow", "fact", "all"], help="Case layer to include. Defaults to content. Repeat to include multiple layers.")
    parser.add_argument("--fail-on-core-fail", action="store_true", help="Exit 1 if core audit has failures.")
    args = parser.parse_args()

    cases = _load_cases(args.case_file)
    report = build_report(cases, args.baseline_name, case_layers=set(args.case_layer or ["content"]))
    report_path = None if args.no_save else save_report(report, args.output_dir)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_summary(report, report_path=report_path)

    if args.fail_on_core_fail and report["summary"]["core_audit_fail_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
