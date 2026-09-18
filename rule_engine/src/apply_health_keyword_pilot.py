# -*- coding: utf-8 -*-
"""Apply the approved precise keyword pilot to two health-food rules."""

import argparse
import json
from datetime import datetime
from pathlib import Path


PILOT_KEYWORDS = {
    'RUID-4d7b4ffb626c816b': {
        'rule_id': 'HF-001',
        'old_hit_terms': [
            '保证', '断言', '绝对有效', '100%有效', '安全无副作用',
            '零副作用', '根治', '彻底治愈', '完全康复',
        ],
        'added_hit_terms': [
            '疗效看得见', '绝对安全', '不会有问题', '全消失', '立竿见影',
        ],
    },
    'RUID-d79610014e487328': {
        'rule_id': 'HF-005',
        'old_hit_terms': [
            '代言人', '推荐', '证明', '亲测', '亲身经历',
            '我用过', '我推荐', '明星', '网红', '专家推荐',
        ],
        'added_hit_terms': [
            '营养学会专家', '科研机构认证', '权威科研机构认证',
        ],
    },
}


def _expected_terms(config):
    return list(dict.fromkeys(config['old_hit_terms'] + config['added_hit_terms']))


def _load_documents(jsonbase_dir):
    documents = {}
    locations = {uid: [] for uid in PILOT_KEYWORDS}
    for path in sorted(Path(jsonbase_dir).rglob('*.json')):
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        documents[path] = payload
        for index, rule in enumerate(payload.get('rules', [])):
            uid = rule.get('rule_uid')
            if uid in locations:
                locations[uid].append((path, index))
    return documents, locations


def apply_keyword_pilot(jsonbase_dir, audit_path=None):
    documents, locations = _load_documents(jsonbase_dir)

    for uid, hits in locations.items():
        if len(hits) != 1:
            raise ValueError(f'target UID must be unique: {uid}; found={len(hits)}')
        path, index = hits[0]
        rule = documents[path]['rules'][index]
        config = PILOT_KEYWORDS[uid]
        if rule.get('rule_id') != config['rule_id']:
            raise ValueError(f'rule_id precondition failed: {uid}')
        try:
            current = rule['detection']['keyword_signals']['hit_terms']
        except (KeyError, TypeError):
            raise ValueError(f'keyword structure precondition failed: {uid}') from None
        if current not in (config['old_hit_terms'], _expected_terms(config)):
            raise ValueError(f'hit_terms precondition failed: {uid}')

    changed_uids = []
    changed_paths = set()
    for uid, hits in locations.items():
        path, index = hits[0]
        terms = documents[path]['rules'][index]['detection']['keyword_signals']['hit_terms']
        expected = _expected_terms(PILOT_KEYWORDS[uid])
        if terms != expected:
            terms[:] = expected
            changed_uids.append(uid)
            changed_paths.add(path)

    for path in sorted(changed_paths):
        path.write_text(
            json.dumps(documents[path], ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )

    audit = {
        'applied_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'changed_rule_uids': changed_uids,
        'target_rule_uids': list(PILOT_KEYWORDS),
        'changed_files': [str(path) for path in sorted(changed_paths)],
        'added_hit_terms': {
            uid: list(config['added_hit_terms']) for uid, config in PILOT_KEYWORDS.items()
        },
        'unchanged_settings': [
            'regex', 'context_signals', 'negative_signals', 'priority',
            'semantic_role', 'semantic_threshold', 'vector_index',
        ],
    }
    if audit_path:
        audit_path = Path(audit_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--jsonbase-dir', required=True)
    parser.add_argument('--audit-path', required=True)
    args = parser.parse_args()
    print(json.dumps(
        apply_keyword_pilot(args.jsonbase_dir, args.audit_path),
        ensure_ascii=False,
        indent=2,
    ))
