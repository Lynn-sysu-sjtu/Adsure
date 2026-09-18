# -*- coding: utf-8 -*-
"""Strict DeepSeek repair for candidate contract failures."""

import argparse
import json
import sys
from pathlib import Path

from deepseek_client import DeepSeekClient
from generate_legal_issue_candidates import MODEL, PROMPT_VERSION, ROOT, _atomic_write_json, _checkpoint_path, _extract_content, _input_digest, load_rule_records
from legal_issue_candidate_pipeline import build_candidate_messages, parse_candidate_response


def strict_contract_instruction():
    return (
        "输出必须同时满足以下硬约束："
        "(1) issue_candidates中有且仅有一个relationship字段等于primary，其余只能是secondary；"
        "(2) default_terminal_outcome只能逐字选择confirmed_violation、evidence_required、proactive_check、no_applicable_rule之一；"
        "(3) evidence_policy.content只能是can_confirm、trigger_only、not_allowed之一，context只能是scope_only、support_or_refute、not_allowed之一，"
        "fact_state只能是support_or_refute、required_to_confirm、not_allowed之一，llm_signal必须是candidate_only；"
        "(4) 不得新增legal_basis、法条、rule_id或任何输入之外的规则标识。不要解释，只输出JSON。"
    )


def strict_repair_candidate(client, record):
    messages = build_candidate_messages(record["rule"], record["source_file"])
    messages[0]["content"] += " " + strict_contract_instruction()
    response = client.create_chat_completion(messages, model=MODEL, temperature=0.0, response_format={"type": "json_object"})
    return parse_candidate_response(_extract_content(response), record["rule"]["rule_uid"])


def repair_failed_candidates(jsonbase_dir, report_dir, client=None):
    report_dir = Path(report_dir)
    summary = json.loads((report_dir / "generation_summary.json").read_text(encoding="utf-8"))
    failed_uids = {item["rule_uid"] for item in summary.get("failures") or []}
    records = {item["rule"]["rule_uid"]: item for item in load_rule_records(jsonbase_dir)}
    client = client or DeepSeekClient(model=MODEL, timeout=90)
    repaired = []
    for uid in sorted(failed_uids):
        record = records[uid]
        candidate = strict_repair_candidate(client, record)
        _atomic_write_json(_checkpoint_path(report_dir, uid), {"rule_uid": uid, "source_file": record["source_file"], "model": MODEL, "prompt_version": PROMPT_VERSION, "input_sha256": _input_digest(record), "attempt": "strict_contract_repair", "candidate": candidate})
        repaired.append(uid)
    result = {"model": MODEL, "repaired_rule_uids": repaired, "repaired_count": len(repaired)}
    _atomic_write_json(report_dir / "strict_repair_summary.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "legal_issue_asset_generation" / "smoke_v1")
    args = parser.parse_args(argv)
    print(json.dumps(repair_failed_candidates(args.jsonbase, args.report_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": sys.exit(main())
