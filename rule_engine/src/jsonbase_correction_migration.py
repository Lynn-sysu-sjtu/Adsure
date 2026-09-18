# -*- coding: utf-8 -*-
"""Controlled JSONBase correction migration for the 2026-09-17 review."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from collections import defaultdict
from pathlib import Path
from typing import Any


def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate the correction contract."""
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rules"), list):
        raise ValueError(f"Invalid correction manifest: {path}")
    seen: set[str] = set()
    for entry in payload["rules"]:
        uid = str(entry.get("rule_uid") or "").strip()
        action = str(entry.get("action") or "").strip()
        if not uid or not action:
            raise ValueError("Every manifest rule requires rule_uid and action")
        if uid in seen:
            raise ValueError(f"Duplicate manifest rule_uid: {uid}")
        seen.add(uid)
    evidence_path = path.with_name('source_repair_evidence_20260917.json')
    if evidence_path.exists():
        evidence_payload = json.loads(evidence_path.read_text(encoding='utf-8'))
        evidence_by_uid = evidence_payload.get('rules') or {}
        for entry in payload['rules']:
            uid = entry['rule_uid']
            evidence = evidence_by_uid.get(uid)
            if evidence is None:
                continue
            evidence = deepcopy(evidence)
            restored_text = str(evidence.get('restored_original_text') or '').strip()
            evidence['sha256'] = sha256_text(restored_text)
            entry['source_evidence'] = evidence
    overrides_path = path.with_name('rule_correction_overrides_20260917.json')
    if overrides_path.exists():
        overrides_payload = json.loads(overrides_path.read_text(encoding='utf-8'))
        overrides = overrides_payload.get('rules') or {}
        entries_by_uid = {entry['rule_uid']: entry for entry in payload['rules']}
        unknown = sorted(set(overrides) - set(entries_by_uid))
        if unknown:
            raise ValueError(f'Overrides contain UIDs outside manifest: {unknown}')
        for uid, override in overrides.items():
            entries_by_uid[uid]['field_changes'] = deepcopy(override.get('changes') or {})
            entries_by_uid[uid]['expected_before'] = deepcopy(override.get('expected_before') or {})
    snapshot_path = path.with_name('rule_correction_preconditions_20260917.json')
    if not snapshot_path.exists():
        raise ValueError('Missing frozen migration preconditions')
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    for entry in payload['rules']:
        entry['expected_rule_sha256'] = snapshot['rule_hashes'][entry['rule_uid']]
    return payload


def _walk_rule_records(value: Any):
    if isinstance(value, dict):
        if value.get("rule_uid"):
            yield value
        for child in value.values():
            yield from _walk_rule_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_rule_records(child)


def inventory_rules(jsonbase_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Index JSONBase records by stable rule_uid without mutating source data."""
    jsonbase_dir = Path(jsonbase_dir)
    inventory: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(jsonbase_dir.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for rule in _walk_rule_records(payload):
            uid = str(rule["rule_uid"]).strip()
            inventory[uid].append({"path": path, "rule": rule})
    return dict(inventory)


def _set_value(target: dict[str, Any], path: tuple[str, ...], value: Any) -> bool:
    current = target
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    key = path[-1]
    if current.get(key) == value:
        return False
    current[key] = deepcopy(value)
    return True


def _get_value(target: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = target
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _atomic_write_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(f'.{path.name}.tmp')
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    temporary.replace(path)


def _apply_entry(rule: dict[str, Any], entry: dict[str, Any]) -> bool:
    changed = False
    action = entry['action']

    field_changes = entry.get('field_changes') or {}
    for dotted_path, expected in (entry.get('expected_before') or {}).items():
        field_path = tuple(dotted_path.split('.'))
        actual = _get_value(rule, field_path)
        desired = field_changes.get(dotted_path)
        if actual != expected and actual != desired:
            raise ValueError(
                'old-value mismatch for {} at {}: {!r}'.format(
                    entry['rule_uid'], dotted_path, actual
                )
            )
    for dotted_path, value in field_changes.items():
        changed |= _set_value(rule, tuple(dotted_path.split('.')), value)

    if action == 'side_path':
        updates = {
            ('asset_disposition',): 'workflow_reference',
            ('direct_conclusion_enabled',): False,
            ('recall', 'trigger_layer'): 'workflow',
            ('recall', 'keyword_enabled'): False,
            ('recall', 'semantic_enabled'): False,
            ('recall', 'semantic_role'): 'disabled',
            ('recall', 'catalog_recall_enabled'): False,
        }
        for field_path, value in updates.items():
            changed |= _set_value(rule, field_path, value)

    if action == 'source_repair':
        evidence = entry.get('source_evidence') or {}
        if evidence.get('status') != 'verified':
            raise ValueError('Unverified source repair: {}'.format(entry['rule_uid']))
        restored_text = str(evidence.get('restored_original_text') or '').strip()
        legal_basis = rule.get('legal_basis')
        if not isinstance(legal_basis, list) or not legal_basis or not isinstance(legal_basis[0], dict):
            raise ValueError('Missing legal_basis[0]: {}'.format(entry['rule_uid']))
        changed |= _set_value(legal_basis[0], ('text',), restored_text)
        repair_record = {
            'status': 'verified',
            'source': evidence.get('source'),
            'locator': evidence.get('locator'),
            'sha256': evidence.get('sha256'),
        }
        changed |= _set_value(rule, ('source_repair',), repair_record)

    if action == 'duplicate_source':
        updates = {
            ('asset_disposition',): 'duplicate_source',
            ('canonical_rule_uid',): entry['canonical_rule_uid'],
            ('direct_conclusion_enabled',): False,
            ('recall', 'trigger_layer'): 'disabled',
            ('recall', 'keyword_enabled'): False,
            ('recall', 'semantic_enabled'): False,
            ('recall', 'semantic_role'): 'disabled',
            ('recall', 'catalog_recall_enabled'): False,
        }
        for field_path, value in updates.items():
            changed |= _set_value(rule, field_path, value)

    roles = rule.get('review_roles') or []
    if roles and 'direct' not in roles:
        changed |= _set_value(rule, ('direct_conclusion_enabled',), False)
        if 'fact_check' not in roles:
            changed |= _set_value(rule, ('recall', 'trigger_layer'), 'workflow')
            for channel in ('keyword_enabled', 'semantic_enabled', 'catalog_recall_enabled'):
                changed |= _set_value(rule, ('recall', channel), False)
            changed |= _set_value(rule, ('recall', 'semantic_role'), 'disabled')
    return bool(changed)


def apply_manifest(
    jsonbase_dir: str | Path,
    manifest_path: str | Path,
    *,
    write: bool = False,
) -> dict[str, Any]:
    '''Apply the correction contract deterministically and report touched records.

    With write=False this performs a complete dry run in memory. Writes are
    atomic per JSON document and only occur for documents containing a changed
    manifest rule.
    '''
    jsonbase_dir = Path(jsonbase_dir)
    manifest = load_manifest(manifest_path)
    entries = {entry['rule_uid']: entry for entry in manifest['rules']}
    inventory = inventory_rules(jsonbase_dir)
    missing = sorted(uid for uid in entries if len(inventory.get(uid, [])) != 1)
    if missing:
        raise ValueError(f'Manifest UIDs must resolve exactly once: {missing}')

    changed_uids: list[str] = []
    changed_files: set[str] = set()
    payloads: dict[Path, Any] = {}
    hashes_before: dict[str, str] = {}
    hashes_after: dict[str, str] = {}
    for path in sorted(jsonbase_dir.rglob('*.json')):
        payload = json.loads(path.read_text(encoding='utf-8'))
        file_changed = False
        for rule in _walk_rule_records(payload):
            uid = str(rule.get('rule_uid') or '').strip()
            entry = entries.get(uid)
            if entry is None:
                continue
            original_hash = hashlib.sha256(
                json.dumps(rule, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
            ).hexdigest()
            if _apply_entry(rule, entry):
                if original_hash != entry['expected_rule_sha256']:
                    raise ValueError(f'old-value mismatch for {uid}: frozen record differs')
                changed_uids.append(uid)
                file_changed = True
        if file_changed:
            payloads[path] = payload
            changed_files.add(str(path))
            hashes_before[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            serialized = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
            hashes_after[str(path)] = hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    if write:
        for path, payload in payloads.items():
            _atomic_write_json(path, payload)

    return {
        'manifest_version': manifest.get('manifest_version'),
        'dry_run': not write,
        'changed_rule_count': len(changed_uids),
        'changed_uids': sorted(changed_uids),
        'changed_files': sorted(changed_files),
        'file_hashes_before': hashes_before,
        'file_hashes_after': hashes_after,
    }


def write_migration_artifacts(
    base_dir: str | Path,
    report: dict[str, Any],
    manifest_path: str | Path,
) -> dict[str, Path]:
    base_dir = Path(base_dir)
    manifest = load_manifest(manifest_path)
    duplicate = manifest.get('canonical_duplicate') or {}
    redirects_path = base_dir / 'assets' / 'rule_uid_redirects_20260917.json'
    report_path = (
        base_dir
        / 'reports'
        / 'jsonbase_correction_20260917'
        / 'migration_report.json'
    )
    redirects_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    redirects = {
        'redirect_version': manifest.get('manifest_version'),
        'redirects': {
            duplicate['duplicate_rule_uid']: duplicate['canonical_rule_uid'],
        },
        'reason': duplicate.get('reason'),
    }
    _atomic_write_json(redirects_path, redirects)
    _atomic_write_json(report_path, report)
    return {
        'uid_redirects': redirects_path,
        'migration_report': report_path,
    }
