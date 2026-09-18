# -*- coding: utf-8 -*-
"""Repair rejected full-batch candidates with error-specific DeepSeek prompts."""

import argparse
import json
import sys
from pathlib import Path

from deepseek_client import DeepSeekClient
from generate_legal_issue_candidates import (
    MODEL,
    PROMPT_VERSION,
    ROOT,
    _atomic_write_json,
    _checkpoint_path,
    _extract_content,
    _input_digest,
    load_rule_records,
)
from legal_issue_candidate_pipeline import build_candidate_messages, parse_candidate_response
from legal_issue_candidate_v3_gate import validate_candidate_core_support


def repair_instruction(error):
    if "stable ASCII identifiers" in error:
        return (
            "上一轮输出的问题标识不符合契约。请重新生成完整候选JSON。"
            "所有category_key、issue_key和check_key必须逐字匹配正则^[A-Z][A-Z0-9_]*$，"
            "只能使用ASCII大写英文字母、数字和下划线。合格示例：category_key=CONTENT，"
            "issue_key=AD_MARKING，check_key=DISCLOSURE_CHECK。严禁中文、空格、斜杠、连字符和括号；"
            "中文只能放在name、definition、description等展示字段。不得修改rule_uid或rule_id。"
        )
    return (
        "上一轮输出的proactive_check未通过核心证据门禁。请重新生成完整候选JSON。"
        "如果title、legal_basis、applies_to、rule_applicability没有直接要求额外资料、资质、披露或流程核验，"
        "proactive_check必须为null。若确需核查，每条core_support.evidence必须从对应source_field逐字复制，"
        "且核查名称、触发条件、要求和材料不得出现核心字段未直接支持的主题。不得概括或联想。"
        "本次门禁错误：" + error
    )


def repair_candidate(client, record, error):
    messages = build_candidate_messages(record["rule"], record["source_file"])
    messages.append({"role": "user", "content": repair_instruction(error)})
    response = client.create_chat_completion(
        messages, model=MODEL, temperature=0.0, response_format={"type": "json_object"}
    )
    raw_content = _extract_content(response)
    try:
        candidate = parse_candidate_response(
            raw_content, record["rule"]["rule_uid"]
        )
    except ValueError as exc:
        if "stable ASCII identifiers" not in str(exc):
            raise
        messages.append({
            "role": "user",
            "content": (
                "只修复上一版完整JSON中的category_key、issue_key和check_key。"
                "将这些值翻译成匹配^[A-Z][A-Z0-9_]*$的稳定英文标识，其他内容不得改变。"
                "上一版完整JSON：" + raw_content
            ),
        })
        response = client.create_chat_completion(
            messages, model=MODEL, temperature=0.0,
            response_format={"type": "json_object"},
        )
        candidate = parse_candidate_response(
            _extract_content(response), record["rule"]["rule_uid"]
        )
    gate_errors = validate_candidate_core_support(candidate, record["rule"])
    if gate_errors:
        raise ValueError("invalid proactive_check core support: " + "; ".join(gate_errors))
    return candidate


def repair_with_retries(client, record, initial_error, attempts=2):
    current_error = initial_error
    last_error = None
    for _ in range(attempts):
        try:
            return repair_candidate(client, record, current_error)
        except Exception as exc:
            last_error = exc
            current_error = str(exc)
    raise last_error


def run_repair(jsonbase_dir, report_dir, shard_index=0, shard_count=1, client=None):
    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be in [0, shard_count)")
    report_dir = Path(report_dir)
    generation = json.loads(
        (report_dir / "generation_summary.json").read_text(encoding="utf-8")
    )
    failed = list(generation.get("failures") or [])[shard_index::shard_count]
    records = {
        item["rule"]["rule_uid"]: item
        for item in load_rule_records(jsonbase_dir)
    }
    client = client or DeepSeekClient(model=MODEL, timeout=90)
    repaired = []
    failures = []
    for item in failed:
        uid = item["rule_uid"]
        record = records[uid]
        try:
            candidate = repair_with_retries(client, record, item["error"])
            _atomic_write_json(_checkpoint_path(report_dir, uid), {
                "rule_uid": uid,
                "source_file": record["source_file"],
                "model": MODEL,
                "prompt_version": PROMPT_VERSION,
                "input_sha256": _input_digest(record),
                "attempt": "full_failure_repair_with_feedback",
                "previous_error": item["error"],
                "candidate": candidate,
            })
            repaired.append(uid)
        except Exception as exc:
            failures.append({
                "rule_uid": uid,
                "previous_error": item["error"],
                "error": str(exc),
            })
    summary = {
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_failure_count": len(failed),
        "repaired_count": len(repaired),
        "failure_count": len(failures),
        "repaired_rule_uids": repaired,
        "failures": failures,
    }
    _atomic_write_json(
        report_dir / f"failure_repair_shard_{shard_index}_summary.json", summary
    )
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args(argv)
    summary = run_repair(
        args.jsonbase, args.report_dir, args.shard_index, args.shard_count
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(bool(summary["failure_count"]))


if __name__ == "__main__":
    sys.exit(main())
