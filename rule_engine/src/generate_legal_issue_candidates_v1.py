# -*- coding: utf-8 -*-
"""Generate three-track legal-issue draft assets with the real DeepSeek API."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from deepseek_client import DeepSeekClient
from legal_asset_drafts import build_jsonbase_snapshot, validate_draft_assets
from legal_issue_candidate_pipeline import (
    build_candidate_messages,
    compile_draft_assets,
    parse_candidate_response,
    select_smoke_rules,
)


ROOT = Path(__file__).resolve().parents[1]
PROMPT_VERSION = "legal_issue_candidate_v1"
MODEL = "deepseek-chat"


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _payload_rules(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("rules") or []
    return []


def load_rule_records(jsonbase_dir):
    root = Path(jsonbase_dir)
    records = []
    seen = set()
    for path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        track = path.relative_to(root).parts[0]
        if track not in {"游戏", "美妆", "保健食品"}:
            continue
        payload = _read_json(path)
        file_meta = (payload.get("meta") or {}) if isinstance(payload, dict) else {}
        legal_sources = (payload.get("legal_sources") or []) if isinstance(payload, dict) else []
        for rule in _payload_rules(payload):
            uid = str(rule.get("rule_uid") or "").strip()
            if not uid:
                raise ValueError(f"missing rule_uid: {relative} / {rule.get('rule_id')}")
            if uid in seen:
                raise ValueError(f"duplicate rule_uid: {uid}")
            seen.add(uid)
            records.append({"rule": rule, "source_file": relative, "track": track, "meta": file_meta, "legal_sources": legal_sources})
    return records


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _input_digest(record):
    messages = build_candidate_messages(record["rule"], record["source_file"])
    raw = json.dumps({"prompt_version": PROMPT_VERSION, "messages": messages}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _checkpoint_path(report_dir, uid):
    safe = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:16]
    return Path(report_dir) / "candidates" / f"{safe}.json"


def _extract_content(response):
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("DeepSeek API response has no message content") from exc


def _call_deepseek(client, record):
    response = client.create_chat_completion(
        build_candidate_messages(record["rule"], record["source_file"]),
        model=MODEL,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return parse_candidate_response(_extract_content(response), record["rule"]["rule_uid"])


def _load_or_generate_candidate(client, record, report_dir):
    uid = record["rule"]["rule_uid"]
    digest = _input_digest(record)
    checkpoint = _checkpoint_path(report_dir, uid)
    if checkpoint.exists():
        saved = _read_json(checkpoint)
        if saved.get("input_sha256") == digest and saved.get("model") == MODEL and saved.get("prompt_version") == PROMPT_VERSION:
            return parse_candidate_response(saved["candidate"], uid), True
    last_error = None
    for attempt in (1, 2):
        try:
            candidate = _call_deepseek(client, record)
            _atomic_write_json(checkpoint, {
                "rule_uid": uid, "source_file": record["source_file"], "model": MODEL,
                "prompt_version": PROMPT_VERSION, "input_sha256": digest, "attempt": attempt,
                "candidate": candidate,
            })
            return candidate, False
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"DeepSeek candidate generation failed for {uid}: {last_error}") from last_error


def _validate_schemas(issue_asset, mapping_asset, check_asset):
    for name, payload in (
        ("legal_issue_directory_draft_schema.json", issue_asset),
        ("rule_issue_mapping_draft_schema.json", mapping_asset),
        ("proactive_check_directory_draft_schema.json", check_asset),
    ):
        Draft202012Validator(_read_json(ROOT / "schema" / name)).validate(payload)


def run_candidate_generation(jsonbase_dir, output_dir, report_dir, client=None, per_track=5):
    jsonbase_dir = Path(jsonbase_dir)
    output_dir = Path(output_dir)
    report_dir = Path(report_dir)
    snapshot_before = build_jsonbase_snapshot(jsonbase_dir)
    all_records = load_rule_records(jsonbase_dir)
    selected = select_smoke_rules(all_records, per_track=per_track)
    client = client or DeepSeekClient(model=MODEL, timeout=90)
    candidates = []
    reused = 0
    failures = []
    for record in selected:
        try:
            candidate, from_checkpoint = _load_or_generate_candidate(client, record, report_dir)
            candidates.append(candidate)
            reused += int(from_checkpoint)
        except Exception as exc:
            failures.append({"rule_uid": record["rule"]["rule_uid"], "source_file": record["source_file"], "error": str(exc)})
    snapshot_after = build_jsonbase_snapshot(jsonbase_dir)
    if snapshot_before != snapshot_after:
        raise RuntimeError("jsonbase changed during candidate generation; refusing to publish drafts")
    summary = {
        "model": MODEL, "prompt_version": PROMPT_VERSION, "selected_rule_count": len(selected),
        "successful_rule_count": len(candidates), "reused_checkpoint_count": reused,
        "failure_count": len(failures), "failures": failures, "source_snapshot": snapshot_before,
        "selected_rules": [{"track": item["track"], "rule_uid": item["rule"]["rule_uid"], "rule_id": item["rule"].get("rule_id"), "dimension": item["rule"].get("dimension"), "source_file": item["source_file"]} for item in selected],
    }
    _atomic_write_json(report_dir / "generation_summary.json", summary)
    if failures:
        raise RuntimeError(f"{len(failures)} DeepSeek candidate batches failed; see generation_summary.json")
    issue_asset, mapping_asset, check_asset = compile_draft_assets(selected, candidates, snapshot_before)
    _validate_schemas(issue_asset, mapping_asset, check_asset)
    validation = validate_draft_assets(issue_asset, mapping_asset, check_asset, [item["rule"] for item in selected])
    _atomic_write_json(report_dir / "validation_report.json", validation)
    if validation["errors"]:
        raise RuntimeError("draft asset validation failed; see validation_report.json")
    for name, payload in (
        ("legal_issue_directory_draft.json", issue_asset),
        ("rule_issue_mapping_draft.json", mapping_asset),
        ("proactive_check_directory_draft.json", check_asset),
    ):
        _atomic_write_json(output_dir / name, payload)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonbase", type=Path, default=ROOT / "jsonbase")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "legal_issue_asset_generation" / "smoke_v1")
    parser.add_argument("--per-track", type=int, default=5)
    args = parser.parse_args(argv)
    summary = run_candidate_generation(args.jsonbase, args.output_dir, args.report_dir, per_track=max(1, args.per_track))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
