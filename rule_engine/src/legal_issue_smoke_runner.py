# -*- coding: utf-8 -*-
"""Run the gated three-track DeepSeek smoke generation from the TDD."""

import argparse
import json
import sys
from pathlib import Path

from deepseek_client import DeepSeekClient
from generate_legal_issue_candidates import (
    MODEL,
    ROOT,
    _atomic_write_json,
    _load_or_generate_candidate,
    _validate_schemas,
    load_rule_records,
)
from legal_asset_drafts import build_jsonbase_snapshot, validate_draft_assets
from legal_issue_candidate_pipeline import compile_draft_assets
from legal_issue_smoke_selection import select_representative_smoke_rules


def run_curated_smoke(jsonbase_dir, output_dir, report_dir, client=None, per_track=5):
    jsonbase_dir = Path(jsonbase_dir); output_dir = Path(output_dir); report_dir = Path(report_dir)
    before = build_jsonbase_snapshot(jsonbase_dir)
    selected = select_representative_smoke_rules(load_rule_records(jsonbase_dir), per_track=per_track)
    client = client or DeepSeekClient(model=MODEL, timeout=90)
    candidates = []
    failures = []
    reused = 0
    for record in selected:
        try:
            candidate, cached = _load_or_generate_candidate(client, record, report_dir)
            candidates.append(candidate); reused += int(cached)
        except Exception as exc:
            failures.append({"rule_uid": record["rule"]["rule_uid"], "source_file": record["source_file"], "error": str(exc)})
    after = build_jsonbase_snapshot(jsonbase_dir)
    if before != after:
        raise RuntimeError("jsonbase changed during DeepSeek smoke generation")
    summary = {
        "model": MODEL, "mode": "three_track_curated_smoke", "per_track": per_track,
        "selected_rule_count": len(selected), "successful_rule_count": len(candidates),
        "reused_checkpoint_count": reused, "failure_count": len(failures), "failures": failures,
        "source_snapshot": before,
        "selected_rules": [{"track": item["track"], "rule_uid": item["rule"]["rule_uid"], "rule_id": item["rule"].get("rule_id"), "title": item["rule"].get("title"), "dimension": item["rule"].get("dimension"), "source_file": item["source_file"]} for item in selected],
    }
    _atomic_write_json(report_dir / "generation_summary.json", summary)
    if failures or len(selected) != per_track * 3:
        raise RuntimeError("DeepSeek smoke generation is incomplete; see generation_summary.json")
    issue_asset, mapping_asset, check_asset = compile_draft_assets(selected, candidates, before)
    _validate_schemas(issue_asset, mapping_asset, check_asset)
    validation = validate_draft_assets(issue_asset, mapping_asset, check_asset, [item["rule"] for item in selected])
    _atomic_write_json(report_dir / "validation_report.json", validation)
    if validation["errors"]:
        raise RuntimeError("draft asset validation failed; see validation_report.json")
    for name, payload in (("legal_issue_directory_draft.json", issue_asset), ("rule_issue_mapping_draft.json", mapping_asset), ("proactive_check_directory_draft.json", check_asset)):
        _atomic_write_json(output_dir / name, payload)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "legal_issue_asset_generation" / "smoke_v1")
    parser.add_argument("--per-track", type=int, default=5)
    args = parser.parse_args(argv)
    print(json.dumps(run_curated_smoke(args.jsonbase, args.output_dir, args.report_dir, per_track=max(1, args.per_track)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
