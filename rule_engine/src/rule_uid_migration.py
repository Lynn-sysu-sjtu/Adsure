# -*- coding: utf-8 -*-
"""Generate and persist deterministic internal UIDs for rule assets."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from kg_rule_store import load_rule_library, save_rule_library


def _text(value):
    return str(value or "").strip()


def _legal_basis_identity(rule):
    basis_items = []
    for basis in rule.get("legal_basis", []) or []:
        if not isinstance(basis, dict):
            continue
        basis_items.append(
            {
                "source": _text(basis.get("source_name") or basis.get("source_id") or basis.get("source")),
                "article": _text(basis.get("article")),
                "text": _text(basis.get("text")),
            }
        )
    return basis_items


def rule_uid_seed(rule):
    """Return the canonical provenance payload used only for missing UIDs."""
    payload = {
        "source_file": _text(rule.get("_source_file")),
        "rule_id": _text(rule.get("rule_id")),
        "title": _text(rule.get("title")),
        "legal_basis": _legal_basis_identity(rule),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def generate_rule_uid(rule):
    digest = hashlib.sha256(rule_uid_seed(rule).encode("utf-8")).hexdigest()
    return "RUID-" + digest[:16]


def assign_missing_rule_uids(rules, uid_factory=generate_rule_uid):
    """Return a migrated deep copy and deterministic change records."""
    migrated = copy.deepcopy(list(rules or []))
    used = {}
    for rule in migrated:
        uid = _text(rule.get("rule_uid"))
        if uid:
            if uid in used:
                raise ValueError(f"rule_uid collision: {uid}")
            used[uid] = rule

    changes = []
    for rule in migrated:
        if _text(rule.get("rule_uid")):
            continue
        uid = _text(uid_factory(rule))
        if not uid:
            raise ValueError("Generated rule_uid is empty")
        if uid in used:
            raise ValueError(f"rule_uid collision: {uid}")
        rule["rule_uid"] = uid
        used[uid] = rule
        changes.append(
            {
                "source_file": _text(rule.get("_source_file")),
                "rule_id": _text(rule.get("rule_id")),
                "rule_uid": uid,
                "title": _text(rule.get("title")),
            }
        )
    changes.sort(key=lambda item: (item["source_file"], item["rule_id"], item["rule_uid"]))
    return migrated, changes


def migrate_library(base_dir, apply=False):
    library = load_rule_library(base_dir)
    migrated, changes = assign_missing_rule_uids(library["data"].get("rules", []))
    if apply and changes:
        library["data"]["rules"] = migrated
        save_rule_library(library)
    return {
        "mode": "apply" if apply else "dry-run",
        "rule_count": len(migrated),
        "change_count": len(changes),
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default="..")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = migrate_library(Path(args.base_dir), apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
