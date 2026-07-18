# -*- coding: utf-8 -*-
"""Generate a focused QC table for medium/high legal_attention conflicts.

Non-destructive: scans jsonbase and writes review tables only.
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from legal_attention_calibration import recommend_route_for_rule

PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_JSONBASE_DIR = PROJECT_BASE / "jsonbase"
DEFAULT_OUTPUT_DIR = PROJECT_BASE / "reports" / "legal_attention_medium_qc"


def _legal_attention(rule):
    value = rule.get("legal_attention") or {}
    return value if isinstance(value, dict) else {}


def _recall(rule):
    value = rule.get("recall") or {}
    return value if isinstance(value, dict) else {}


def _trigger_layer(rule):
    return _recall(rule).get("trigger_layer") or "content"


def _is_high(value):
    return value in {"高", "high"}


def load_rules(jsonbase_dir=DEFAULT_JSONBASE_DIR):
    rows = []
    for path in sorted(Path(jsonbase_dir).rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            rows.append({"_load_error": str(exc), "_source_file": str(path)})
            continue
        if not isinstance(data, dict):
            continue
        for rule in data.get("rules", []) or []:
            item = dict(rule)
            item["_source_file"] = str(path)
            rows.append(item)
    return rows


def conflict_flags(rule):
    la = _legal_attention(rule)
    recall = _recall(rule)
    current_route = la.get("default_route") or ""
    old_route = (rule.get("routing") or {}).get("default_route") or ""
    trigger_layer = _trigger_layer(rule)
    fact_level = la.get("fact_verification_level")
    interpretation = la.get("legal_interpretation_level")
    fixability = la.get("operator_fixability")
    risk_severity = la.get("risk_severity") or rule.get("risk_level")
    semantic_enabled = recall.get("semantic_enabled")
    semantic_role = recall.get("semantic_role")

    flags = []
    if old_route and current_route and old_route != current_route:
        flags.append("legal_attention/routing不一致")
    if _is_high(rule.get("risk_level")) and current_route == "operator_direct":
        flags.append("高风险规则但运营直接处理")
    if current_route == "legal_review_required" and fixability == "direct_fixable" and fact_level == "none":
        flags.append("运营可直接修但流转法务")
    if current_route == "operator_direct" and fact_level == "heavy":
        flags.append("重事实核验但运营直接处理")
    if trigger_layer == "fact" and semantic_enabled is True:
        flags.append("fact规则仍开启普通语义召回")
    if trigger_layer == "workflow" and (semantic_enabled is True or semantic_role not in {None, "", "disabled"}):
        flags.append("workflow规则仍可能进入普通召回")
    if trigger_layer == "content" and fact_level == "heavy":
        flags.append("content规则依赖重事实核验")
    if current_route in {"operator_direct", "operator_supply_docs"} and interpretation == "high" and _is_high(risk_severity):
        flags.append("高解释难度高风险但未进法务")
    return flags


def priority_from(rule, recommendation, flags):
    if any(flag in flags for flag in [
        "重事实核验但运营直接处理",
        "fact规则仍开启普通语义召回",
        "workflow规则仍可能进入普通召回",
        "高解释难度高风险但未进法务",
    ]):
        return "high"
    if recommendation.get("review_priority") == "high":
        return "high"
    if flags or recommendation.get("review_priority") == "medium":
        return "medium"
    return "low"


def build_rows(rules):
    rows = []
    for rule in rules:
        if rule.get("_load_error"):
            continue
        la = _legal_attention(rule)
        recall = _recall(rule)
        recommendation = recommend_route_for_rule(rule)
        flags = conflict_flags(rule)
        review_priority = priority_from(rule, recommendation, flags)
        if review_priority == "low":
            continue
        rows.append(
            {
                "review_priority": review_priority,
                "rule_uid": rule.get("rule_uid"),
                "rule_id": rule.get("rule_id"),
                "title": rule.get("title"),
                "dimension": rule.get("dimension"),
                "risk_level": rule.get("risk_level"),
                "trigger_layer": _trigger_layer(rule),
                "semantic_enabled": recall.get("semantic_enabled"),
                "semantic_role": recall.get("semantic_role"),
                "current_route": la.get("default_route"),
                "old_routing_route": (rule.get("routing") or {}).get("default_route"),
                "recommended_route": recommendation.get("recommended_route"),
                "route_changed": recommendation.get("route_changed"),
                "trigger_clarity": la.get("trigger_clarity"),
                "legal_interpretation_level": la.get("legal_interpretation_level"),
                "fact_verification_level": la.get("fact_verification_level"),
                "risk_severity": la.get("risk_severity"),
                "operator_fixability": la.get("operator_fixability"),
                "calibration_status": la.get("calibration_status"),
                "conflict_flags": "；".join(flags),
                "recommendation_reasons": "；".join(recommendation.get("reasons", [])),
                "source_file": rule.get("_source_file"),
            }
        )
    priority_order = {"high": 0, "medium": 1, "low": 2}
    rows.sort(key=lambda row: (priority_order.get(row["review_priority"], 9), row.get("trigger_layer") or "", row.get("rule_id") or ""))
    return rows


def summarize(rows):
    summary = {"row_count": len(rows), "by_priority": {}, "by_layer": {}, "by_route": {}, "route_changed_count": 0}
    for row in rows:
        for key, field in [("by_priority", "review_priority"), ("by_layer", "trigger_layer"), ("by_route", "current_route")]:
            value = row.get(field) or "<empty>"
            summary[key][value] = summary[key].get(value, 0) + 1
        if row.get("route_changed"):
            summary["route_changed_count"] += 1
    return summary


def write_outputs(rows, summary, output_dir=DEFAULT_OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_dir / f"{timestamp}_legal_attention_medium_qc"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    json_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fieldnames = list(rows[0].keys()) if rows else ["review_priority"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description="Generate medium/high priority legal_attention QC table.")
    parser.add_argument("--jsonbase-dir", default=str(DEFAULT_JSONBASE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    rows = build_rows(load_rules(args.jsonbase_dir))
    summary = summarize(rows)
    json_path, csv_path = write_outputs(rows, summary, args.output_dir)
    print(json.dumps({"summary": summary, "json": str(json_path), "csv": str(csv_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()