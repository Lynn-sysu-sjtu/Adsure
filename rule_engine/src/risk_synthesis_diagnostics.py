# -*- coding: utf-8 -*-
"""Generate diagnostics for risk synthesis failures in baseline reports.

This script is non-destructive. It reads a baseline report JSON and writes CSV/JSON
rows that explain which matched rules contributed to risk mismatches.
"""

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = PROJECT_BASE / "test_reports"
DEFAULT_OUTPUT_DIR = PROJECT_BASE / "reports" / "risk_synthesis_diagnostics"
DEFAULT_JSONBASE_DIR = PROJECT_BASE / "jsonbase"


def latest_report(report_dir=DEFAULT_REPORT_DIR):
    paths = sorted(Path(report_dir).glob("*.json"), key=lambda path: path.stat().st_mtime)
    if not paths:
        raise FileNotFoundError(f"No baseline reports found in {report_dir}")
    return paths[-1]


def load_rule_uid_index(jsonbase_dir=DEFAULT_JSONBASE_DIR):
    index = {}
    for path in sorted(Path(jsonbase_dir).rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for rule in data.get("rules", []) or []:
            uid = rule.get("rule_uid")
            if uid:
                index[uid] = rule
    return index

def _legal_attention(rule):
    value = rule.get("legal_attention") or {}
    return value if isinstance(value, dict) else {}


def _is_high(value):
    return value in {"高", "high"}


def build_rows(report, rule_index=None):
    rows = []
    for case in report.get("cases", []) or []:
        checks = case.get("checks", {}) or {}
        risk = case.get("risk_assessment", {}) or {}
        if checks.get("final_risk_ok", True) and not risk.get("risk_disagreement"):
            continue

        expected = case.get("expected", {}) or {}
        actual = case.get("actual", {}) or {}
        details = actual.get("matched_rule_details", []) or []
        high_rules = [rule for rule in details if _is_high(rule.get("risk_level"))]
        if not high_rules:
            high_rules = details

        for rule in high_rules:
            source_rule = rule_index.get(rule.get("rule_uid"), {})
            la = _legal_attention(source_rule) or _legal_attention(rule)
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "case_name": case.get("name"),
                    "core_audit_ok": checks.get("core_audit_ok"),
                    "final_risk_ok": checks.get("final_risk_ok"),
                    "expected_risk": expected.get("expected_risk_level"),
                    "rule_engine_risk": risk.get("rule_engine_risk_level"),
                    "llm_risk": risk.get("llm_risk_level"),
                    "final_risk": risk.get("final_risk_level"),
                    "final_risk_source": risk.get("final_risk_source"),
                    "risk_disagreement": risk.get("risk_disagreement"),
                    "rule_id": rule.get("rule_id"),
                    "rule_uid": rule.get("rule_uid"),
                    "title": rule.get("title"),
                    "trigger_layer": rule.get("trigger_layer"),
                    "recall_channel": rule.get("recall_channel"),
                    "rule_risk_level": rule.get("risk_level"),
                    "legal_attention_default_route": rule.get("legal_attention_default_route") or la.get("default_route"),
                    "legal_interpretation_level": la.get("legal_interpretation_level"),
                    "fact_verification_level": la.get("fact_verification_level"),
                    "risk_severity": la.get("risk_severity"),
                    "operator_fixability": la.get("operator_fixability"),
                    "confidence": la.get("confidence"),
                    "calibration_status": la.get("calibration_status"),
                }
            )
    return rows


def summarize(rows):
    summary = {
        "row_count": len(rows),
        "case_count": len({row["case_id"] for row in rows}),
        "high_rule_count": sum(1 for row in rows if _is_high(row.get("rule_risk_level"))),
        "by_route": {},
        "by_trigger_layer": {},
        "by_fixability": {},
    }
    for key, field in [
        ("by_route", "legal_attention_default_route"),
        ("by_trigger_layer", "trigger_layer"),
        ("by_fixability", "operator_fixability"),
    ]:
        counts = {}
        for row in rows:
            value = row.get(field) or "<empty>"
            counts[value] = counts.get(value, 0) + 1
        summary[key] = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    return summary


def write_outputs(rows, summary, report_path, output_dir=DEFAULT_OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = output_dir / f"{timestamp}_risk_synthesis_diagnostics"
    payload = {
        "source_report": str(report_path),
        "summary": summary,
        "rows": rows,
    }
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fieldnames = list(rows[0].keys()) if rows else ["case_id"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description="Generate risk synthesis diagnostics from a baseline report.")
    parser.add_argument("--report", default=None, help="Baseline report JSON. Defaults to latest in test_reports.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else latest_report()
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    rule_index = load_rule_uid_index()
    rows = build_rows(report, rule_index=rule_index)
    summary = summarize(rows)
    json_path, csv_path = write_outputs(rows, summary, report_path, args.output_dir)
    print(json.dumps({"source_report": str(report_path), "summary": summary, "json": str(json_path), "csv": str(csv_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()