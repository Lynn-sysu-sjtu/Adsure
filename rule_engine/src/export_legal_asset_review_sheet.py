# -*- coding: utf-8 -*-
"""Export the DeepSeek smoke drafts as a human-review workbook."""

import argparse
import json
from pathlib import Path

from generate_legal_issue_candidates import ROOT, load_rule_records
from legal_asset_review import assess_candidate_quality, export_review_workbook


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "assets")
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "legal_issue_asset_generation" / "smoke_v1" / "三赛道法律问题资产人工审核表.xlsx")
    args = parser.parse_args(argv)
    read = lambda name: json.loads((args.assets / name).read_text(encoding="utf-8"))
    issues = read("legal_issue_directory_draft.json"); mappings = read("rule_issue_mapping_draft.json"); checks = read("proactive_check_directory_draft.json")
    records = {item["rule"]["rule_uid"]: item for item in load_rule_records(args.jsonbase)}
    warnings = assess_candidate_quality(issues, mappings, checks, records)
    warning_path = args.output.with_name("quality_warnings.json")
    warning_path.write_text(json.dumps({"warning_count": len(warnings), "warnings": warnings}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    export_review_workbook(args.output, issues, mappings, checks, warnings, records)
    print(json.dumps({"workbook": str(args.output), "warning_report": str(warning_path), "warning_count": len(warnings)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
