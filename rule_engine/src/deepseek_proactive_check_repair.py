# -*- coding: utf-8 -*-
"""Use DeepSeek to repair incomplete proactive-check candidate structures."""

import argparse
import json
import sys
from pathlib import Path

from deepseek_client import DeepSeekClient
from generate_legal_issue_candidates import MODEL, PROMPT_VERSION, ROOT, _atomic_write_json, _checkpoint_path, _extract_content, _input_digest, load_rule_records
from legal_issue_candidate_pipeline import build_candidate_messages, parse_candidate_response


CHECK_TYPES = {"fact_verification", "qualification", "disclosure", "workflow"}
REQUIRED_KEYS = {"check_key", "name", "check_type", "applicability", "trigger_conditions", "requirement", "required_materials", "default_severity"}


def proactive_check_errors(check):
    if check is None:
        return []
    if not isinstance(check, dict):
        return ["proactive_check"]
    errors = sorted(REQUIRED_KEYS - set(check))
    if check.get("check_type") not in CHECK_TYPES and "check_type" not in errors:
        errors.append("check_type")
    applicability = check.get("applicability")
    if not isinstance(applicability, dict) or not {"industries", "platforms", "material_types"} <= set(applicability):
        errors.append("applicability")
    conditions = check.get("trigger_conditions")
    if not isinstance(conditions, dict) or not {"all", "any", "exclude"} <= set(conditions):
        errors.append("trigger_conditions")
    if check.get("default_severity") not in {"高", "中", "低"} and "default_severity" not in errors:
        errors.append("default_severity")
    return sorted(set(errors))


def proactive_repair_instruction():
    return (
        "只修复proactive_check结构并返回完整候选JSON。若当前规则仅凭正文即可判断，或规则本身不要求额外资料/流程核验，proactive_check必须为null，不得猜测。"
        "若确需主动核查，必须逐字包含check_key、name、check_type、applicability、trigger_conditions、requirement、required_materials、default_severity；"
        "check_type只能是fact_verification、qualification、disclosure、workflow之一；applicability必须含industries/platforms/material_types数组；"
        "trigger_conditions必须含all/any/exclude数组；default_severity只能是高/中/低。不得新增法条、规则ID或法律原文。"
    )


def repair_candidate(client, record, current_candidate):
    messages = build_candidate_messages(record["rule"], record["source_file"])
    messages.append({"role": "user", "content": proactive_repair_instruction() + "\n待修复候选：" + json.dumps(current_candidate, ensure_ascii=False, separators=(",", ":"))})
    response = client.create_chat_completion(messages, model=MODEL, temperature=0.0, response_format={"type": "json_object"})
    candidate = parse_candidate_response(_extract_content(response), record["rule"]["rule_uid"])
    errors = proactive_check_errors(candidate.get("proactive_check"))
    if errors:
        raise ValueError("invalid proactive_check after DeepSeek repair: " + ",".join(errors))
    return candidate


def repair_invalid_checkpoints(jsonbase_dir, report_dir, client=None):
    report_dir = Path(report_dir)
    records = {item["rule"]["rule_uid"]: item for item in load_rule_records(jsonbase_dir)}
    invalid = []
    for path in sorted((report_dir / "candidates").glob("*.json")):
        saved = json.loads(path.read_text(encoding="utf-8")); candidate = saved["candidate"]
        errors = proactive_check_errors(candidate.get("proactive_check"))
        if errors:
            invalid.append((path, candidate["rule_uid"], candidate, errors))
    client = client or DeepSeekClient(model=MODEL, timeout=90)
    repaired = []
    for path, uid, current, old_errors in invalid:
        record = records[uid]; candidate = repair_candidate(client, record, current)
        _atomic_write_json(_checkpoint_path(report_dir, uid), {"rule_uid": uid, "source_file": record["source_file"], "model": MODEL, "prompt_version": PROMPT_VERSION, "input_sha256": _input_digest(record), "attempt": "proactive_check_repair", "previous_errors": old_errors, "candidate": candidate})
        repaired.append(uid)
    result = {"model": MODEL, "invalid_count": len(invalid), "repaired_count": len(repaired), "repaired_rule_uids": repaired}
    _atomic_write_json(report_dir / "proactive_check_repair_summary.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "legal_issue_asset_generation" / "smoke_v1")
    args = parser.parse_args(argv)
    print(json.dumps(repair_invalid_checkpoints(args.jsonbase, args.report_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": sys.exit(main())
