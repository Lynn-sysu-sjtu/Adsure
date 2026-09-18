# -*- coding: utf-8 -*-
"""Default V3 entry point for DeepSeek legal-issue candidate generation."""

import json

import generate_legal_issue_candidates_v1 as _v1
from legal_issue_candidate_v3_gate import validate_candidate_core_support


PROMPT_VERSION = "legal_issue_candidate_v3"
MODEL = _v1.MODEL
ROOT = _v1.ROOT

# The V1 implementation resolves these globals at call time. Changing the
# module-level version invalidates V1 checkpoints while retaining its tested
# retry, snapshot and atomic-write behavior.
_v1.PROMPT_VERSION = PROMPT_VERSION

_read_json = _v1._read_json
_payload_rules = _v1._payload_rules
load_rule_records = _v1.load_rule_records
_atomic_write_json = _v1._atomic_write_json
_input_digest = _v1._input_digest
_checkpoint_path = _v1._checkpoint_path
_extract_content = _v1._extract_content
_v1_call_deepseek = _v1._call_deepseek
_v1_load_or_generate_candidate = _v1._load_or_generate_candidate


def _call_deepseek(client, record):
    candidate = _v1_call_deepseek(client, record)
    errors = validate_candidate_core_support(candidate, record["rule"])
    if not errors:
        return candidate

    messages = _v1.build_candidate_messages(record["rule"], record["source_file"])
    messages.append({
        "role": "user",
        "content": (
            "上一版候选的Python确定性校验失败，必须修复后返回完整JSON。"
            "不得新增或改写规则依据；proactive_check为null时无需core_support；"
            "非null时，每条core_support.evidence必须从其source_field对应的输入值中逐字复制。"
            "校验错误：" + "; ".join(errors) +
            "\n待修复候选：" + json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        ),
    })
    response = client.create_chat_completion(
        messages, model=MODEL, temperature=0.0, response_format={"type": "json_object"}
    )
    repaired = _v1.parse_candidate_response(
        _extract_content(response), record["rule"]["rule_uid"]
    )
    repair_errors = validate_candidate_core_support(repaired, record["rule"])
    if repair_errors:
        raise ValueError(
            "invalid proactive_check core support after DeepSeek repair: "
            + "; ".join(repair_errors)
        )
    return repaired


_v1._call_deepseek = _call_deepseek


def _load_or_generate_candidate(client, record, report_dir):
    candidate, reused = _v1_load_or_generate_candidate(client, record, report_dir)
    errors = validate_candidate_core_support(candidate, record["rule"])
    if errors:
        raise ValueError("invalid proactive_check core support: " + "; ".join(errors))
    return candidate, reused


_v1._load_or_generate_candidate = _load_or_generate_candidate
_validate_schemas = _v1._validate_schemas
run_candidate_generation = _v1.run_candidate_generation
main = _v1.main


if __name__ == "__main__":
    raise SystemExit(main())
