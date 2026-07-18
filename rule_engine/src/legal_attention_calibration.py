# -*- coding: utf-8 -*-
"""Build MVP calibration tables for legal_attention.default_route.

This script is intentionally non-destructive: it reads jsonbase and optional
baseline reports, then writes JSON/CSV review tables. It never writes back to
rule JSON files.
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_BASE / "reports" / "legal_attention_calibration_mvp"
ROUTE_VALUES = {"operator_direct", "operator_supply_docs", "legal_review_required"}


def _route_label(value):
    return {
        "operator_direct": "运营直接修改",
        "operator_supply_docs": "运营补充资料",
        "legal_review_required": "法务复核",
    }.get(value or "", value or "")


def _risk_is_high(value):
    return value in {"high", "高"}


def _rule_trigger_layer(rule):
    return (rule.get("recall", {}) or {}).get("trigger_layer") or "content"


def _legal_attention(rule):
    value = rule.get("legal_attention") or {}
    return value if isinstance(value, dict) else {}


def recommend_route_for_rule(rule):
    """Return a conservative route recommendation for one rule.

    The recommendation is a review hint, not an automatic truth. The caller can
    decide whether to write it back after human review.
    """
    legal_attention = _legal_attention(rule)
    current_route = legal_attention.get("default_route")
    if current_route not in ROUTE_VALUES:
        current_route = ""

    trigger_layer = _rule_trigger_layer(rule)
    trigger_clarity = legal_attention.get("trigger_clarity")
    interpretation = legal_attention.get("legal_interpretation_level")
    fact_level = legal_attention.get("fact_verification_level")
    risk_severity = legal_attention.get("risk_severity") or rule.get("risk_level")
    fixability = legal_attention.get("operator_fixability")

    recommended_route = current_route
    reasons = []
    review_priority = "low"
    confidence = "medium"

    clear_direct_fix = (
        trigger_clarity == "clear"
        and interpretation == "low"
        and fact_level == "none"
        and fixability == "direct_fixable"
    )
    if current_route == "legal_review_required" and clear_direct_fix:
        recommended_route = "operator_direct"
        reasons.append("可能过度流转法务：触发清楚、无需事实核验且运营可直接修复。")
        review_priority = "high"
        confidence = "high"

    if current_route == "legal_review_required" and fact_level in {"light", "heavy"} and interpretation != "high":
        if fixability in {"guided_fixable", "direct_fixable", None, ""}:
            recommended_route = "operator_supply_docs"
            reasons.append("可能应先由运营补充资料：主要矛盾是事实核验，不一定需要立即占用法务。")
            review_priority = "high"

    if current_route == "operator_direct" and fact_level == "heavy":
        recommended_route = "operator_supply_docs"
        reasons.append("可能低估资料需求：规则依赖重事实核验，应先要求运营补充证明材料。")
        review_priority = "high"
        confidence = "high"

    if current_route in {"operator_direct", "operator_supply_docs"} and interpretation == "high" and _risk_is_high(risk_severity):
        recommended_route = "legal_review_required"
        reasons.append("可能低估法务注意力：高解释难度且后果风险较高，建议法务复核。")
        review_priority = "high"

    if current_route == "operator_supply_docs" and fact_level == "none" and fixability == "direct_fixable":
        recommended_route = "operator_direct"
        reasons.append("可能不需要补资料：无需外部事实且运营可直接修改。")
        if review_priority == "low":
            review_priority = "medium"

    if trigger_layer == "workflow":
        reasons.append("workflow 规则当前不进入普通文案审核，建议作为专项链路单独校准。")
        if review_priority == "low":
            review_priority = "medium"

    old_route = (rule.get("routing") or {}).get("default_route")
    if old_route and current_route and old_route != current_route:
        reasons.append("legal_attention.default_route 与旧 routing.default_route 不一致。")
        if review_priority == "low":
            review_priority = "medium"

    if not reasons:
        reasons.append("未发现明显字段冲突；可低优先级抽检。")

    if recommended_route == current_route and review_priority == "low":
        confidence = "low"

    return {
        "current_route": current_route,
        "recommended_route": recommended_route or current_route,
        "route_changed": bool(recommended_route and recommended_route != current_route),
        "review_priority": review_priority,
        "confidence": confidence,
        "reasons": reasons,
    }


def load_rules(jsonbase_dir):
    rules = []
    for path in sorted(Path(jsonbase_dir).rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rules.append({"_load_error": str(exc), "_source_file": str(path)})
            continue
        for rule in data.get("rules", []) if isinstance(data, dict) else []:
            item = dict(rule)
            item["_source_file"] = str(path)
            rules.append(item)
    return rules


def load_baseline_report(path):
    if not path:
        return None
    report_path = Path(path)
    if not report_path.exists():
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


def find_latest_baseline_report(report_dir):
    report_dir = Path(report_dir)
    if not report_dir.exists():
        return None
    candidates = sorted(report_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _baseline_failure_signals(baseline_report):
    signals = defaultdict(lambda: {"count": 0, "case_ids": [], "directions": set()})
    if not baseline_report:
        return signals
    for case in baseline_report.get("cases", []) or []:
        checks = case.get("checks") or {}
        if checks.get("routing_ok", True):
            continue
        expected_route = (case.get("expected") or {}).get("expected_routing")
        actual_route = (case.get("actual") or {}).get("routing")
        if expected_route == "运营" and actual_route == "法务":
            direction = "expected_operator_actual_legal"
        elif expected_route == "法务" and actual_route == "运营":
            direction = "expected_legal_actual_operator"
        else:
            direction = "routing_mismatch_other"
        for rule_id in (case.get("actual") or {}).get("matched_rule_ids", []) or []:
            item = signals[rule_id]
            item["count"] += 1
            item["case_ids"].append(case.get("case_id"))
            item["directions"].add(direction)
    return signals


def build_calibration_rows(rules, baseline_report=None, include_low_priority=False):
    signals = _baseline_failure_signals(baseline_report)
    rows = []
    for rule in rules:
        if rule.get("_load_error"):
            rows.append({
                "rule_id": "",
                "title": "JSON load error",
                "source_file": rule.get("_source_file"),
                "review_priority": "high",
                "reasons": rule.get("_load_error"),
            })
            continue
        recommendation = recommend_route_for_rule(rule)
        signal = signals.get(rule.get("rule_id"), {"count": 0, "case_ids": [], "directions": set()})
        baseline_count = signal["count"]
        if baseline_count and recommendation["review_priority"] == "low":
            recommendation["review_priority"] = "medium"
            recommendation["reasons"].append("该规则出现在 routing 失败 case 的命中规则池中，建议人工复核。")
        if not include_low_priority and recommendation["review_priority"] == "low" and not baseline_count:
            continue

        legal_attention = _legal_attention(rule)
        row = {
            "rule_id": rule.get("rule_id"),
            "rule_uid": rule.get("rule_uid"),
            "title": rule.get("title"),
            "dimension": rule.get("dimension"),
            "risk_level": rule.get("risk_level"),
            "source_file": rule.get("_source_file"),
            "trigger_layer": _rule_trigger_layer(rule),
            "current_legal_attention_route": recommendation["current_route"],
            "current_legal_attention_route_label": _route_label(recommendation["current_route"]),
            "routing_default_route": (rule.get("routing") or {}).get("default_route"),
            "recommended_route": recommendation["recommended_route"],
            "recommended_route_label": _route_label(recommendation["recommended_route"]),
            "route_changed": recommendation["route_changed"],
            "review_priority": recommendation["review_priority"],
            "confidence": recommendation["confidence"],
            "reason": "；".join(recommendation["reasons"]),
            "trigger_clarity": legal_attention.get("trigger_clarity"),
            "legal_interpretation_level": legal_attention.get("legal_interpretation_level"),
            "fact_verification_level": legal_attention.get("fact_verification_level"),
            "risk_severity": legal_attention.get("risk_severity"),
            "operator_fixability": legal_attention.get("operator_fixability"),
            "baseline_failure_count": baseline_count,
            "baseline_failure_case_ids": ",".join(case_id for case_id in signal["case_ids"] if case_id),
            "baseline_failure_direction": ",".join(sorted(signal["directions"])),
            "calibration_status": "pending_human_review",
        }
        rows.append(row)
    rows.sort(key=lambda row: (
        {"high": 0, "medium": 1, "low": 2}.get(row.get("review_priority"), 9),
        -int(row.get("baseline_failure_count") or 0),
        row.get("rule_id") or "",
    ))
    return rows


def summarize_rows(rows, total_rules=0, baseline_report_path=None):
    return {
        "total_rules": total_rules,
        "row_count": len(rows),
        "high_priority_count": sum(1 for row in rows if row.get("review_priority") == "high"),
        "medium_priority_count": sum(1 for row in rows if row.get("review_priority") == "medium"),
        "route_change_suggestion_count": sum(1 for row in rows if row.get("route_changed")),
        "baseline_failure_rule_count": sum(1 for row in rows if int(row.get("baseline_failure_count") or 0) > 0),
        "baseline_report_path": str(baseline_report_path) if baseline_report_path else "",
    }


def write_outputs(rows, summary, output_dir=DEFAULT_OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"{timestamp}_legal_attention_calibration_mvp.json"
    csv_path = output_dir / f"{timestamp}_legal_attention_calibration_mvp.csv"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scope": "legal_attention_default_route_mvp_calibration",
        "non_destructive": True,
        "summary": summary,
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fieldnames = list(rows[0].keys()) if rows else ["rule_id", "review_priority", "reason"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description="Build non-destructive legal_attention.default_route calibration table.")
    parser.add_argument("--base-dir", default=str(PROJECT_BASE))
    parser.add_argument("--jsonbase-dir", default=None)
    parser.add_argument("--baseline-report", default=None)
    parser.add_argument("--latest-baseline", action="store_true", help="Use latest JSON report under test_reports if --baseline-report is not set.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--include-low-priority", action="store_true")
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    jsonbase_dir = Path(args.jsonbase_dir) if args.jsonbase_dir else base_dir / "jsonbase"
    baseline_path = Path(args.baseline_report) if args.baseline_report else None
    if not baseline_path and args.latest_baseline:
        baseline_path = find_latest_baseline_report(base_dir / "test_reports")
    baseline_report = load_baseline_report(baseline_path) if baseline_path else None
    rules = load_rules(jsonbase_dir)
    rows = build_calibration_rows(rules, baseline_report=baseline_report, include_low_priority=args.include_low_priority)
    summary = summarize_rows(rows, total_rules=sum(1 for rule in rules if not rule.get("_load_error")), baseline_report_path=baseline_path)
    json_path, csv_path = write_outputs(rows, summary, args.output_dir)

    print("Legal attention calibration MVP")
    print("-" * 72)
    print(f"jsonbase_dir: {jsonbase_dir}")
    print(f"baseline_report: {baseline_path or ''}")
    print(f"total_rules: {summary['total_rules']}")
    print(f"row_count: {summary['row_count']}")
    print(f"high_priority_count: {summary['high_priority_count']}")
    print(f"medium_priority_count: {summary['medium_priority_count']}")
    print(f"route_change_suggestion_count: {summary['route_change_suggestion_count']}")
    print(f"baseline_failure_rule_count: {summary['baseline_failure_rule_count']}")
    print(f"json: {json_path}")
    print(f"csv: {csv_path}")


if __name__ == "__main__":
    main()