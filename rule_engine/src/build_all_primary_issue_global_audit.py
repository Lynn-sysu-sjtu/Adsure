# -*- coding: utf-8 -*-
"""Build one draft-only audit workbook across every primary issue root."""

from __future__ import annotations

import json
from pathlib import Path

from all_primary_issue_fingerprint_review import (
    PROCESS_ROOTS,
    ROOT_NAMES,
    atomic_json,
    compile_global_audit,
    export_global_audit_workbook,
)
from generate_legal_issue_candidates import load_rule_records
from legal_asset_drafts import build_jsonbase_snapshot


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_JSONBASE_SHA256 = "7d3ac278ac2a43a26f6c70be847314c1e432d76ae7c15fbf767cfb4ab5a79cc2"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    assets_root = ROOT / "assets" / "all_primary_issue_review_draft_v0.1"
    report_root = ROOT / "reports" / "all_primary_issue_fingerprint_review_v01"
    all_mappings = []
    root_summaries = []
    for root_id in PROCESS_ROOTS:
        assets = load_json(assets_root / root_id / "review_assets.json")
        all_mappings.extend(assets["mappings"])
        root_summaries.append({
            "root_id": root_id,
            "root_name": assets["root_name"],
            "rule_count": len(assets["mappings"]),
            "issue_count": sum(item.get("level") == 3 for item in assets["nodes"]),
            "duplicate_group_count": sum(item["duplicate_count"] > 1 for item in assets["canonical_groups"]),
            "scope_conflict_count": sum(bool((item.get("fingerprint") or {}).get("source_scope_conflict")) for item in assets["mappings"]),
            "root_conflict_count": sum(bool((item.get("fingerprint") or {}).get("root_scope_conflict")) for item in assets["mappings"]),
            "proactive_candidate_count": len(assets["proactive_candidates"]),
            "low_or_medium_count": sum((item.get("fingerprint") or {}).get("confidence") != "high" for item in assets["mappings"]),
        })

    endorsement = load_json(ROOT / "assets" / "endorsement_rule_mapping_draft_v0.3.json")
    endorsement_mappings = []
    for source in endorsement["mappings"]:
        item = dict(source)
        item["root_id"] = "ENDORSEMENT_REVIEW"
        fingerprint = dict(item.get("fingerprint") or {})
        fingerprint.setdefault("root_scope_conflict", False)
        fingerprint.setdefault("suggested_root_id", "ENDORSEMENT_REVIEW")
        item["fingerprint"] = fingerprint
        endorsement_mappings.append(item)
    all_mappings.extend(endorsement_mappings)
    endorsement_summary = load_json(ROOT / "reports" / "endorsement_fingerprint_pilot_v02" / "full_v03_review_fixed" / "pilot_summary.json")
    root_summaries.append({
        "root_id": "ENDORSEMENT_REVIEW",
        "root_name": ROOT_NAMES["ENDORSEMENT_REVIEW"],
        "rule_count": len(endorsement_mappings),
        "issue_count": endorsement_summary.get("cluster_count"),
        "duplicate_group_count": endorsement_summary.get("duplicate_canonical_group_count"),
        "scope_conflict_count": endorsement_summary.get("source_scope_conflict_count"),
        "root_conflict_count": 0,
        "proactive_candidate_count": endorsement_summary.get("proactive_check_count"),
        "low_or_medium_count": endorsement_summary.get("low_or_medium_fingerprint_count"),
    })

    expected_mappings = load_json(ROOT / "assets" / "rule_issue_mapping_draft_v0.3.json")["mappings"]
    records = load_rule_records(ROOT / "jsonbase")
    records_by_uid = {item["rule"]["rule_uid"]: item for item in records}
    audit = compile_global_audit(all_mappings, expected_mappings, records_by_uid)
    snapshot = build_jsonbase_snapshot(ROOT / "jsonbase")
    if snapshot["jsonbase_sha256"] != EXPECTED_JSONBASE_SHA256:
        raise RuntimeError("jsonbase SHA-256 changed; stop before publishing audit outputs")
    if audit["coverage"]["unexpected_rule_uids"]:
        raise RuntimeError("global audit contains rule_uid values outside the 857-rule mapping")

    workbook_path = report_root / "全部一级问题统一人工审核表_v0.1.xlsx"
    audit_path = report_root / "global_audit_v0.1.json"
    summary_path = report_root / "global_audit_summary_v0.1.json"
    export_global_audit_workbook(workbook_path, audit, root_summaries, snapshot)
    atomic_json(audit_path, audit)
    atomic_json(summary_path, {
        "asset_status": "draft",
        "coverage": audit["coverage"],
        "root_count": len(root_summaries),
        "duplicate_group_count": len(audit["duplicate_groups"]),
        "cross_root_overlap_count": len(audit["cross_root_overlaps"]),
        "scope_conflict_count": len(audit["scope_conflicts"]),
        "root_conflict_count": len(audit["root_conflicts"]),
        "proactive_candidate_count": len(audit["proactive_candidates"]),
        "low_or_medium_count": len(audit["low_or_medium"]),
        "source_snapshot": snapshot,
        "outputs": {"workbook": str(workbook_path), "audit_json": str(audit_path)},
    })
    print(json.dumps(load_json(summary_path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
