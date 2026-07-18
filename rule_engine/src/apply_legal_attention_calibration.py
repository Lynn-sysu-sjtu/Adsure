# -*- coding: utf-8 -*-
"""Apply human-confirmed legal_attention route calibration rows.

This script writes back only rows that have been explicitly accepted by a human
review workflow. It updates legal_attention.default_route and, by default, keeps
legacy routing.default_route in sync so later fallback logic and reports do not
contradict the calibrated route.
"""

import argparse
import csv
import json
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROUTE_VALUES = {"operator_direct", "operator_supply_docs", "legal_review_required"}
PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_CSV = PROJECT_BASE / "reports" / "legal_attention_calibration_mvp" / "20260715_130231_legal_attention_calibration_mvp.csv"
DEFAULT_REPORT_DIR = PROJECT_BASE / "reports" / "legal_attention_calibration_apply"


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def load_confirmed_rows(csv_path, accepted_priority="high"):
    rows = []
    skipped = []
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row_number, row in enumerate(reader, start=2):
            route = (row.get("recommended_route") or "").strip()
            priority = (row.get("review_priority") or "").strip()
            if priority != accepted_priority or not _truthy(row.get("route_changed")):
                skipped.append({"row_number": row_number, "rule_id": row.get("rule_id"), "reason": "not accepted filter"})
                continue
            if route not in ROUTE_VALUES:
                skipped.append({"row_number": row_number, "rule_id": row.get("rule_id"), "reason": "invalid recommended_route"})
                continue
            if not row.get("source_file") or not row.get("rule_id"):
                skipped.append({"row_number": row_number, "rule_id": row.get("rule_id"), "reason": "missing source_file or rule_id"})
                continue
            rows.append({**row, "_row_number": row_number})
    return rows, skipped


def _find_rule(rules, row):
    rule_uid = row.get("rule_uid")
    if rule_uid:
        matches = [rule for rule in rules if rule.get("rule_uid") == rule_uid]
        if len(matches) == 1:
            return matches[0]

    rule_id = row.get("rule_id")
    matches = [rule for rule in rules if rule.get("rule_id") == rule_id]
    if len(matches) == 1:
        return matches[0]

    title = row.get("title")
    if title:
        title_matches = [rule for rule in matches if rule.get("title") == title]
        if len(title_matches) == 1:
            return title_matches[0]

    dimension = row.get("dimension")
    if title and dimension:
        scoped_matches = [rule for rule in matches if rule.get("title") == title and rule.get("dimension") == dimension]
        if len(scoped_matches) == 1:
            return scoped_matches[0]
    return None


def _apply_row(rule, row, calibrated_at, sync_routing=True):
    legal_attention = rule.setdefault("legal_attention", {})
    if not isinstance(legal_attention, dict):
        legal_attention = {}
        rule["legal_attention"] = legal_attention

    old_legal_route = legal_attention.get("default_route")
    old_routing_route = (rule.get("routing") or {}).get("default_route")
    new_route = row["recommended_route"]

    legal_attention["default_route"] = new_route
    legal_attention["calibration_status"] = "human_confirmed"
    legal_attention["calibrated_at"] = calibrated_at
    legal_attention["calibration_source"] = "legal_attention_calibration_mvp_csv"
    legal_attention["calibration_row_number"] = row.get("_row_number")
    if row.get("reason"):
        legal_attention["route_reason"] = "人工校准接受 recommended_route：" + row["reason"]

    if sync_routing:
        routing = rule.setdefault("routing", {})
        if isinstance(routing, dict):
            routing["default_route"] = new_route

    return {
        "rule_id": rule.get("rule_id"),
        "title": rule.get("title"),
        "old_legal_attention_route": old_legal_route,
        "old_routing_default_route": old_routing_route,
        "new_route": new_route,
        "sync_routing": sync_routing,
    }


def apply_confirmed_routes(csv_path=DEFAULT_CSV, accepted_priority="high", sync_routing=True, dry_run=False, report_dir=DEFAULT_REPORT_DIR):
    csv_path = Path(csv_path)
    confirmed_rows, skipped_rows = load_confirmed_rows(csv_path, accepted_priority=accepted_priority)
    rows_by_file = defaultdict(list)
    for row in confirmed_rows:
        rows_by_file[Path(row["source_file"])].append(row)

    calibrated_at = datetime.now().isoformat(timespec="seconds")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    updated = []
    errors = []
    backups = []

    for source_file, rows in sorted(rows_by_file.items(), key=lambda item: str(item[0])):
        try:
            data = json.loads(source_file.read_text(encoding="utf-8"))
            rules = data.get("rules", []) if isinstance(data, dict) else []
            file_updates = []
            for row in rows:
                rule = _find_rule(rules, row)
                if rule is None:
                    errors.append({"source_file": str(source_file), "rule_id": row.get("rule_id"), "reason": "rule not found or duplicate"})
                    continue
                file_updates.append(_apply_row(rule, row, calibrated_at=calibrated_at, sync_routing=sync_routing))
            if file_updates and not dry_run:
                backup = source_file.with_name(source_file.name + ".bak_apply_legal_attention_" + timestamp)
                shutil.copy2(source_file, backup)
                backups.append(str(backup))
                source_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            updated.extend({**item, "source_file": str(source_file)} for item in file_updates)
        except Exception as exc:
            errors.append({"source_file": str(source_file), "reason": str(exc)})

    summary = {
        "csv_path": str(csv_path),
        "accepted_priority": accepted_priority,
        "sync_routing": sync_routing,
        "dry_run": dry_run,
        "confirmed_rows": len(confirmed_rows),
        "updated_rules": len(updated),
        "skipped_rows": len(skipped_rows),
        "error_count": len(errors),
        "backups": backups,
        "updated": updated,
        "skipped": skipped_rows,
        "errors": errors,
    }

    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / (timestamp + "_apply_legal_attention_calibration_summary.json")
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["report_path"] = str(report_path)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Apply human-confirmed high-priority legal_attention route calibration rows.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Calibration CSV path.")
    parser.add_argument("--accepted-priority", default="high", help="Only apply rows with this review_priority.")
    parser.add_argument("--no-sync-routing", action="store_true", help="Do not sync legacy routing.default_route.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = apply_confirmed_routes(
        csv_path=args.csv,
        accepted_priority=args.accepted_priority,
        sync_routing=not args.no_sync_routing,
        dry_run=args.dry_run,
    )
    print("Apply legal_attention calibration")
    print("-" * 72)
    for key in ["csv_path", "accepted_priority", "sync_routing", "dry_run", "confirmed_rows", "updated_rules", "skipped_rows", "error_count", "report_path"]:
        print(f"{key}: {summary.get(key)}")
    if summary.get("backups"):
        print("backups:")
        for path in summary["backups"]:
            print("  " + path)
    if summary.get("errors"):
        print("errors:")
        for item in summary["errors"][:20]:
            print("  " + json.dumps(item, ensure_ascii=False))


if __name__ == "__main__":
    main()