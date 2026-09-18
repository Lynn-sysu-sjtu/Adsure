# -*- coding: utf-8 -*-
"""Validation and read-only safeguards for draft legal-issue assets."""

import hashlib
import json
from pathlib import Path


ASSET_FILENAMES = (
    "legal_issue_directory_draft.json",
    "rule_issue_mapping_draft.json",
    "proactive_check_directory_draft.json",
)
REVIEW_STATUSES = {"pending", "approved", "rejected", "needs_revision"}


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _rules_from_payload(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("rules") or []
    return []


def build_jsonbase_snapshot(jsonbase_dir):
    root = Path(jsonbase_dir)
    digest = hashlib.sha256()
    rule_count = 0
    files = sorted(root.rglob("*.json"), key=lambda path: path.as_posix())
    for path in files:
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
        rule_count += len(_rules_from_payload(json.loads(content.decode("utf-8-sig"))))
    return {"file_count": len(files), "rule_count": rule_count, "jsonbase_sha256": digest.hexdigest()}


def _validate_reviews(records, label, errors):
    for record in records:
        review = record.get("review") or {}
        status = review.get("status")
        if status not in REVIEW_STATUSES:
            errors.append(f"{label} has invalid review status: {status}")
        if status == "approved":
            if not str(review.get("reviewer") or "").strip():
                errors.append(f"{label} approved record requires reviewer")
            if not str(review.get("reviewed_at") or "").strip():
                errors.append(f"{label} approved record requires reviewed_at")


def _validate_issue_tree(issues, errors):
    issue_ids = [item.get("issue_id") for item in issues]
    known = {item for item in issue_ids if item}
    if len(known) != len(issue_ids):
        errors.append("issue_id values must be present and unique")
    parents = {}
    for issue in issues:
        issue_id = issue.get("issue_id")
        parent = issue.get("parent_issue_id")
        if parent and parent not in known:
            errors.append(f"unknown parent_issue_id: {parent}")
        parents[issue_id] = parent
    for start in known:
        seen = set()
        current = start
        while current:
            if current in seen:
                errors.append(f"issue tree cycle detected at {current}")
                break
            seen.add(current)
            current = parents.get(current)


def validate_draft_assets(issue_asset, mapping_asset, check_asset, rules):
    errors = []
    rules_by_uid = {str(rule.get("rule_uid")): rule for rule in rules or [] if str(rule.get("rule_uid") or "").strip()}
    issues = issue_asset.get("issues") or []
    mappings = mapping_asset.get("mappings") or []
    checks = check_asset.get("checks") or []
    _validate_issue_tree(issues, errors)
    issue_ids = {item.get("issue_id") for item in issues}
    check_ids = [item.get("check_id") for item in checks]
    known_check_ids = {item for item in check_ids if item}
    if len(known_check_ids) != len(check_ids):
        errors.append("check_id values must be present and unique")
    for issue in issues:
        for uid in issue.get("candidate_rule_uids") or []:
            if uid not in rules_by_uid:
                errors.append(f"unknown rule_uid in issue directory: {uid}")
    mapped_uids = set()
    for mapping in mappings:
        uid = mapping.get("rule_uid")
        if uid not in rules_by_uid:
            errors.append(f"unknown rule_uid in mapping: {uid}")
        if uid in mapped_uids:
            errors.append(f"duplicate rule_uid mapping: {uid}")
        mapped_uids.add(uid)
        referenced = [mapping.get("primary_issue_id")] + list(mapping.get("secondary_issue_ids") or [])
        for issue_id in referenced:
            if issue_id not in issue_ids:
                errors.append(f"unknown issue_id in mapping: {issue_id}")
        for check_id in mapping.get("proactive_check_ids") or []:
            if check_id not in known_check_ids:
                errors.append(f"unknown proactive check in mapping: {check_id}")
    for check in checks:
        for issue_id in check.get("trigger_issue_ids") or []:
            if issue_id not in issue_ids:
                errors.append(f"unknown trigger issue in proactive check: {issue_id}")
        for uid in check.get("basis_rule_uids") or []:
            rule = rules_by_uid.get(uid)
            if not rule:
                errors.append(f"unknown basis rule_uid in proactive check: {uid}")
            elif not (rule.get("legal_basis") or []):
                errors.append(f"basis rule_uid has empty legal_basis: {uid}")
    _validate_reviews(issues, "issue", errors)
    _validate_reviews(mappings, "mapping", errors)
    _validate_reviews(checks, "proactive check", errors)
    return {"valid": not errors, "errors": errors, "warnings": []}


def load_runtime_legal_assets(asset_dir):
    root = Path(asset_dir)
    payloads = [_read_json(root / name) for name in ASSET_FILENAMES]
    for payload in payloads:
        if payload.get("asset_status") != "approved":
            raise ValueError("draft legal assets cannot be loaded at runtime")
        records = payload.get("issues") or payload.get("mappings") or payload.get("checks") or []
        if any((record.get("review") or {}).get("status") != "approved" for record in records):
            raise ValueError("unapproved legal asset record cannot be loaded at runtime")
    return tuple(payloads)
