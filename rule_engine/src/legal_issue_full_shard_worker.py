# -*- coding: utf-8 -*-
"""Generate one non-overlapping shard of the full DeepSeek candidate batch."""

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
    load_rule_records,
)
from legal_issue_candidate_pipeline import select_smoke_rules


def partition_records(records, shard_index, shard_count):
    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be in [0, shard_count)")
    return list(records)[shard_index::shard_count]


def run_shard(jsonbase_dir, report_dir, shard_index, shard_count, client=None):
    selected = select_smoke_rules(load_rule_records(jsonbase_dir), per_track=10000)
    records = partition_records(selected, shard_index, shard_count)
    client = client or DeepSeekClient(model=MODEL, timeout=90)
    successful = 0
    reused = 0
    failures = []
    for record in records:
        try:
            _, cached = _load_or_generate_candidate(client, record, report_dir)
            successful += 1
            reused += int(cached)
        except Exception as exc:
            failures.append({
                "rule_uid": record["rule"]["rule_uid"],
                "source_file": record["source_file"],
                "error": str(exc),
            })
    summary = {
        "model": MODEL,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_rule_count": len(records),
        "successful_rule_count": successful,
        "reused_checkpoint_count": reused,
        "failure_count": len(failures),
        "failures": failures,
    }
    _atomic_write_json(Path(report_dir) / f"shard_{shard_index}_summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, default=4)
    args = parser.parse_args(argv)
    summary = run_shard(
        args.jsonbase, args.report_dir, args.shard_index, args.shard_count
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(bool(summary["failure_count"]))


if __name__ == "__main__":
    sys.exit(main())
