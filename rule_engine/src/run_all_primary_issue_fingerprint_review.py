# -*- coding: utf-8 -*-

import argparse
import json
from pathlib import Path

from all_primary_issue_fingerprint_review import PROCESS_ROOTS, export_root_workbook, run_root
from deepseek_client import DeepSeekClient
from generate_legal_issue_candidates import load_rule_records


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--roots", nargs="*", default=list(PROCESS_ROOTS))
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--assets-dir", type=Path, default=ROOT / "assets" / "all_primary_issue_review_draft_v0.1")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "all_primary_issue_fingerprint_review_v01")
    args = parser.parse_args(argv)
    taxonomy = json.loads((ROOT / "assets" / "legal_issue_taxonomy_draft_v0.3.json").read_text(encoding="utf-8"))["issues"]
    mappings = json.loads((ROOT / "assets" / "rule_issue_mapping_draft_v0.3.json").read_text(encoding="utf-8"))["mappings"]
    records = load_rule_records(ROOT / "jsonbase")
    client = DeepSeekClient(timeout=180)
    summaries = []
    for root_id in args.roots:
        assets = run_root(client, root_id, taxonomy, mappings, records, args.assets_dir, args.report_dir, args.batch_size)
        workbook = export_root_workbook(args.report_dir / root_id / f"{root_id}_人工审核表.xlsx", assets)
        summaries.append({
            "root_id": root_id, "root_name": assets["root_name"], "rule_count": len(assets["mappings"]),
            "issue_count": sum(item["level"] == 3 for item in assets["nodes"]),
            "duplicate_group_count": sum(item["duplicate_count"] > 1 for item in assets["canonical_groups"]),
            "scope_conflict_count": sum(bool(item["fingerprint"].get("source_scope_conflict")) for item in assets["mappings"]),
            "root_conflict_count": sum(bool(item["fingerprint"].get("root_scope_conflict")) for item in assets["mappings"]),
            "proactive_candidate_count": len(assets["proactive_candidates"]), "workbook": str(workbook),
        })
        print(json.dumps(summaries[-1], ensure_ascii=False))
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "run_summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
