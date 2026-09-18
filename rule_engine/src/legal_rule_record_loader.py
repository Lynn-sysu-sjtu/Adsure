# -*- coding: utf-8 -*-
"""Load general and three-track rules for full legal-issue asset generation."""

import json
from pathlib import Path


TRACKS = {"游戏", "美妆", "保健食品"}


def _rules(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("rules") or []
    return []


def load_all_rule_records(jsonbase_dir):
    root = Path(jsonbase_dir)
    records = []
    seen = set()
    for path in sorted(root.rglob("*.json"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        track = "通用" if len(relative.parts) == 1 else relative.parts[0]
        if track != "通用" and track not in TRACKS:
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        for rule in _rules(payload):
            uid = str(rule.get("rule_uid") or "").strip()
            if not uid:
                raise ValueError(f"missing rule_uid: {relative.as_posix()} / {rule.get('rule_id')}")
            if uid in seen:
                raise ValueError(f"duplicate rule_uid: {uid}")
            seen.add(uid)
            records.append({"rule": rule, "source_file": relative.as_posix(), "track": track})
    return records
