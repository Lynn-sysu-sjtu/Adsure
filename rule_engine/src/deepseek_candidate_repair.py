# -*- coding: utf-8 -*-
"""Repair DeepSeek candidates that violate the single-primary issue contract."""

import argparse
import json
import sys
from pathlib import Path

from deepseek_client import DeepSeekClient
from generate_legal_issue_candidates import MODEL, PROMPT_VERSION, ROOT, _atomic_write_json, _checkpoint_path, _extract_content, _input_digest, load_rule_records
from legal_issue_candidate_pipeline import build_candidate_messages, parse_candidate_response


def repair_candidate(client, record):
    messages = build_candidate_messages(record["rule"], record["source_file"])
    messages[0]["content"] += (
        " 本次是契约修复：issue_candidates中必须有且仅有一个relationship=primary；"
        "如规则涉及多个问题，其余只能标为secondary。必须自行选择最直接、最核心的规制问题作为primary。"
    )
    response = client.create_chat_completion(messages, model=MODEL, temperature=0.0, response_format={"type": "json_object"})
    candidate = parse_candidate_response(_extract_content(response), record["rule"]["rule_uid"])
    candidate["_repair_model"] = MODEL
    return candidate


def repair_failed_candidates(jsonbase_dir, report_dir, client=None):
    report_dir = Path(report_dir)
    summary = json.loads((report_dir / "generation_summary.json").read_text(encoding="utf-8"))
    failed_uids = {item["rule_uid"] for item in summary.get("failures") or []}
    records = {item["rule"]["rule_uid"]: item for item in load_rule_records(jsonbase_dir)}
    client = client or DeepSeekClient(model=MODEL, timeout=90)
    repaired = []
    for uid in sorted(failed_uids):
        record = records[uid]
        candidate = repair_candidate(client, record)
        checkpoint = _checkpoint_path(report_dir, uid)
        _atomic_write_json(checkpoint, {
            "rule_uid": uid, "source_file": record["source_file"], "model": MODEL,
            "prompt_version": PROMPT_VERSION, "input_sha256": _input_digest(record),
            "attempt": "contract_repair", "candidate": candidate,
        })
        repaired.append(uid)
    result = {"model": MODEL, "repaired_rule_uids": repaired, "repaired_count": len(repaired)}
    _atomic_write_json(report_dir / "repair_summary.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "legal_issue_asset_generation" / "smoke_v1")
    args = parser.parse_args(argv)
    print(json.dumps(repair_failed_candidates(args.jsonbase, args.report_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
