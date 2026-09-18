# -*- coding: utf-8 -*-
"""Align semantic scope for the two approved health-food vector-pilot rules."""

import argparse
import json
from datetime import datetime
from pathlib import Path


TARGET_UIDS = ('RUID-4d7b4ffb626c816b', 'RUID-d79610014e487328')
EXPECTED_INDUSTRIES = ['保健食品']
OLD_PRODUCT_CATEGORIES = ['保健食品']
OLD_MATERIAL_TYPES = [
    '图文文案', 'Banner文字', '详情页文字', '直播话术',
    '短视频脚本中的文字内容', '私域文案',
]
NEW_MATERIAL_TYPE = '短视频脚本'


def _locations(jsonbase_dir):
    hits = {uid: [] for uid in TARGET_UIDS}
    documents = {}
    for path in sorted(Path(jsonbase_dir).rglob('*.json')):
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        documents[path] = payload
        for index, rule in enumerate(payload.get('rules', [])):
            uid = rule.get('rule_uid')
            if uid in hits:
                hits[uid].append((path, index))
    return documents, hits


def apply_scope_pilot(jsonbase_dir, audit_path=None):
    documents, hits = _locations(jsonbase_dir)
    for uid, locations in hits.items():
        if len(locations) != 1:
            raise ValueError(f'target UID must be unique: {uid}; found={len(locations)}')
        path, index = locations[0]
        scope = documents[path]['rules'][index].get('applies_to') or {}
        if scope.get('industries') != EXPECTED_INDUSTRIES:
            raise ValueError(f'industry scope precondition failed: {uid}')
        if scope.get('product_categories') not in (OLD_PRODUCT_CATEGORIES, []):
            raise ValueError(f'product category scope precondition failed: {uid}')
        material_types = scope.get('material_types') or []
        allowed_material_types = [OLD_MATERIAL_TYPES, OLD_MATERIAL_TYPES + [NEW_MATERIAL_TYPE]]
        if material_types not in allowed_material_types:
            raise ValueError(f'material type scope precondition failed: {uid}')

    changed = []
    changed_paths = set()
    for uid, locations in hits.items():
        path, index = locations[0]
        scope = documents[path]['rules'][index]['applies_to']
        before_categories = list(scope.get('product_categories') or [])
        before_material_types = list(scope.get('material_types') or [])
        scope['product_categories'] = []
        if NEW_MATERIAL_TYPE not in scope['material_types']:
            scope['material_types'].append(NEW_MATERIAL_TYPE)
        if before_categories != scope['product_categories'] or before_material_types != scope['material_types']:
            changed.append(uid)
            changed_paths.add(path)

    for path in sorted(changed_paths):
        path.write_text(json.dumps(documents[path], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    audit = {
        'applied_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'changed_rule_uids': changed,
        'target_rule_uids': list(TARGET_UIDS),
        'changed_files': [str(path) for path in sorted(changed_paths)],
        'scope_change': {
            'industries': EXPECTED_INDUSTRIES,
            'product_categories': [],
            'added_material_type': NEW_MATERIAL_TYPE,
        },
        'unchanged_settings': ['platforms', 'channels', 'audiences', 'semantic_role', 'threshold', 'keywords'],
    }
    if audit_path:
        audit_path = Path(audit_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--jsonbase-dir', required=True)
    parser.add_argument('--audit-path', required=True)
    args = parser.parse_args()
    print(json.dumps(apply_scope_pilot(args.jsonbase_dir, args.audit_path), ensure_ascii=False, indent=2))
