# -*- coding: utf-8 -*-
"""Run the DeepSeek endorsement fingerprint v0.2 review pilot."""

import argparse
import json
from pathlib import Path

from deepseek_client import DeepSeekClient
from endorsement_fingerprint_pilot_v02 import run_pilot
from generate_legal_issue_candidates import load_rule_records


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--assets-dir", type=Path, default=ROOT / "assets")
    parser.add_argument(
        "--report-dir", type=Path,
        default=ROOT / "reports" / "endorsement_fingerprint_pilot_v02",
    )
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--smoke-limit", type=int)
    args = parser.parse_args(argv)
    summary = run_pilot(
        load_rule_records(args.jsonbase), DeepSeekClient(timeout=180),
        args.assets_dir, args.report_dir,
        batch_size=max(1, args.batch_size), smoke_limit=args.smoke_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["rule_uid_preserved"] and not summary["source_less_issue_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
