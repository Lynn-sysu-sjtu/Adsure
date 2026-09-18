# -*- coding: utf-8 -*-
"""Apply the approved two-rule health-food semantic-vector pilot."""

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path


PILOT_RULES = {
    'RUID-4d7b4ffb626c816b': {
        'rule_id': 'HF-001',
        'old_vector_text': '本产品保证100%有效?绝对安全无副作用?我们断言这款保健品能根治你的问题?保证?断言?绝对有效?1',
        'new_vector_text': '保健食品广告不得对产品功效或安全性作出确定、绝对、无条件的断言或保证。',
        'scenarios': [
            {
                'scenario_id': 'efficacy_guarantee',
                'vector_text': '保健食品宣称服用几天保证见效，功效必然实现，身体问题全消失，效果立竿见影',
                'enabled': True,
            },
            {
                'scenario_id': 'safety_guarantee',
                'vector_text': '保健食品宣称纯天然所以绝对安全，任何人食用都不会有问题，没有任何副作用',
                'enabled': True,
            },
        ],
    },
    'RUID-d79610014e487328': {
        'rule_id': 'HF-005',
        'old_vector_text': 'XX明星推荐本品，亲测有效，我推荐给大家，网红力荐，专家证明，亲身经历，我用过效果很好，代言人推荐，',
        'new_vector_text': '保健食品广告不得借个人、专家或机构名义对产品作推荐、认证或效果证明。',
        'scenarios': [
            {
                'scenario_id': 'endorser_recommendation',
                'vector_text': '保健食品广告借明星、网红、用户或专家名义亲测推荐，声称使用后有效并向消费者作效果证明',
                'enabled': True,
            },
            {
                'scenario_id': 'institutional_endorsement',
                'vector_text': '保健食品广告借科研单位、学术机构、营养学会或行业协会名义作权威推荐、认证或功效证明',
                'enabled': True,
            },
        ],
    },
}


def _load_documents(jsonbase_dir):
    documents = []
    locations = {uid: [] for uid in PILOT_RULES}
    for path in sorted(Path(jsonbase_dir).rglob('*.json')):
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
        documents.append((path, payload))
        for index, rule in enumerate(payload.get('rules', [])):
            uid = rule.get('rule_uid')
            if uid in locations:
                locations[uid].append((path, payload, index))
    return documents, locations


def apply_pilot(jsonbase_dir, audit_path=None):
    documents, locations = _load_documents(jsonbase_dir)
    for uid, hits in locations.items():
        if len(hits) != 1:
            raise ValueError(f'target UID must be unique: {uid}; found={len(hits)}')
        rule = hits[0][1]['rules'][hits[0][2]]
        config = PILOT_RULES[uid]
        recall = rule.get('recall') or {}
        current_text = recall.get('vector_text')
        if current_text not in {config['old_vector_text'], config['new_vector_text']}:
            raise ValueError(f'vector_text precondition failed: {uid}')

    changed = []
    files_to_write = {}
    for uid, hits in locations.items():
        path, payload, index = hits[0]
        rule = payload['rules'][index]
        recall = rule.setdefault('recall', {})
        config = PILOT_RULES[uid]
        before = copy.deepcopy(recall)
        recall['vector_text'] = config['new_vector_text']
        recall['semantic_scenarios'] = copy.deepcopy(config['scenarios'])
        if recall != before:
            changed.append(uid)
            files_to_write[path] = payload

    for path, payload in files_to_write.items():
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    audit = {
        'applied_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'changed_rule_uids': changed,
        'target_rule_uids': list(PILOT_RULES),
        'changed_files': [str(path) for path in sorted(files_to_write)],
        'semantic_role_changes': [],
        'threshold_changes': [],
        'scenarios': {uid: config['scenarios'] for uid, config in PILOT_RULES.items()},
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
    print(json.dumps(apply_pilot(args.jsonbase_dir, args.audit_path), ensure_ascii=False, indent=2))
