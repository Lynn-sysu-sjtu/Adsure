"""Read-only frozen pre-migration fixtures for integration tests."""
import hashlib
import json
import shutil
import subprocess

from jsonbase_correction_migration import inventory_rules, load_manifest, _walk_rule_records


def copy_frozen_jsonbase(root, destination):
    shutil.copytree(root / 'jsonbase', destination)
    manifest = load_manifest(root / 'assets/jsonbase_correction_manifest_20260917.json')
    entries = {e['rule_uid']: e for e in manifest['rules']}
    inventory = inventory_rules(destination)
    paths = {rows[0]['path'] for uid, rows in inventory.items() if uid in entries}
    for path in paths:
        relative = path.relative_to(destination)
        repository_path = 'rule_engine/jsonbase/' + relative.as_posix()
        raw = subprocess.check_output(['git', 'show', 'HEAD:' + repository_path], cwd=root.parent)
        payload = json.loads(raw.decode('utf-8'))
        for rule in _walk_rule_records(payload):
            entry = entries.get(rule['rule_uid'])
            if entry is None:
                continue
            digest = hashlib.sha256(
                json.dumps(rule, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
            ).hexdigest()
            if digest != entry['expected_rule_sha256']:
                raise ValueError('Git fixture differs from frozen migration contract')
        path.write_bytes(raw)
