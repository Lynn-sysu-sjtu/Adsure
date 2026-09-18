# -*- coding: utf-8 -*-
"""Run the review-only DeepSeek legal issue taxonomy pipeline."""

import argparse
import json
from pathlib import Path

from deepseek_client import DeepSeekClient
from generate_legal_issue_candidates import load_rule_records
from legal_issue_taxonomy_v01 import read_json, run_pipeline


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=ROOT / "assets")
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "legal_issue_taxonomy_v01")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args(argv)
    issue_asset = read_json(args.assets / "legal_issue_directory_draft.json")
    mapping_asset = read_json(args.assets / "rule_issue_mapping_draft.json")
    records = {item["rule"]["rule_uid"]: item for item in load_rule_records(args.jsonbase)}
    summary = run_pipeline(
        DeepSeekClient(timeout=180), issue_asset, mapping_asset, records,
        args.output, args.assets, batch_size=args.batch_size, workers=args.workers,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["validation"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
