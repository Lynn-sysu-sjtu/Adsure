# -*- coding: utf-8 -*-
"""Export auditable UID expectations without mutating source test datasets."""

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from legal_rule_record_loader import load_all_rule_records


BASE = Path(__file__).resolve().parents[1]
WORKSPACE = BASE.parents[1]
SOURCE_NAMES = ('20260906保健食品测试样例集.json', '20260908美妆测试样例集.json')
STATUSES = {'resolved', 'replace_expected_rule', 'fact_check_only', 'invalid_expectation', 'unresolved'}
FIELDS = ('expectation_type', 'legacy_rule_id', 'rule_uid', 'resolution_status',
          'matched_rule_id', 'matched_document_title', 'matched_article_or_locator',
          'matched_provision_excerpt', 'expected_channel', 'resolution_reason')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_bindings(case, bindings, current_uids):
    expected = case['expected']
    requested = [(kind, rule_id) for field, kind in
                 (('must_recall_rule_ids', 'must_recall'), ('must_not_recall_rule_ids', 'must_not_recall'))
                 for rule_id in expected.get(field, [])]
    actual = [(item.get('expectation_type'), item.get('legacy_rule_id')) for item in bindings]
    if Counter(requested) != Counter(actual):
        raise ValueError(f"{case['case_id']}: missing or extra binding: {Counter(requested) - Counter(actual)}")
    for item in bindings:
        missing = set(FIELDS) - set(item)
        if missing:
            raise ValueError(f"{case['case_id']}: missing binding fields: {sorted(missing)}")
        status, uid = item['resolution_status'], item['rule_uid']
        if status not in STATUSES:
            raise ValueError(f"{case['case_id']}: invalid status: {status}")
        if status in {'resolved', 'replace_expected_rule'}:
            if uid not in current_uids:
                raise ValueError(f"{case['case_id']}: unknown UID: {uid}")
            if item['expected_channel'] != 'content':
                raise ValueError(f"{case['case_id']}: non-content UID target: {uid}")
        elif uid is not None:
            raise ValueError(f"{case['case_id']}: unscorable binding contains UID: {uid}")
        if not item['resolution_reason']:
            raise ValueError(f"{case['case_id']}: empty reason")


def migrate_case(case, bindings, current_uids):
    validate_bindings(case, bindings, current_uids)
    result = copy.deepcopy(case)
    expected = result['expected']
    for kind, field in (('must_recall', 'must_recall_rule_uids'),
                        ('must_not_recall', 'must_not_recall_rule_uids')):
        expected[field] = list(dict.fromkeys(item['rule_uid'] for item in bindings
            if item['expectation_type'] == kind and
            item['resolution_status'] in {'resolved', 'replace_expected_rule'}))
    expected['expected_rule_bindings'] = copy.deepcopy(bindings)
    return result


def rule_inventory():
    records = load_all_rule_records(BASE / 'jsonbase')
    return {record['rule']['rule_uid']: record for record in records}


def _evidence(case, rule_id):
    for kind in ('legal_provisions', 'platform_provisions'):
        for provision in case['expected'].get(kind, []):
            if provision.get('rule_id') == rule_id:
                return provision
    return {}


def build_binding(case, kind, legacy_id, decision, inventory):
    status = decision['status']
    uid = decision.get('uid')
    evidence = _evidence(case, legacy_id)
    rule = inventory.get(uid, {}).get('rule', {})
    source = inventory.get(uid, {}).get('source_file', '')
    basis = rule.get('legal_basis') or []
    basis = next((item for item in basis if isinstance(item, dict) and
                  (not evidence.get('article') or str(item.get('article', '')).startswith(
                      str(evidence['article']).split('第')[0] or str(evidence['article'])[:3]))),
                 basis[0] if basis else {})
    if not isinstance(basis, dict):
        basis = {}
    return {
        'expectation_type': kind, 'legacy_rule_id': legacy_id, 'rule_uid': uid,
        'resolution_status': status, 'matched_rule_id': rule.get('rule_id'),
        'matched_document_title': evidence.get('document_title') or (source if uid else None),
        'matched_article_or_locator': evidence.get('article') or evidence.get('locator') or basis.get('article'),
        'matched_provision_excerpt': (evidence.get('provision_text') or basis.get('text') or '')[:320] or None,
        'expected_channel': decision.get('channel', 'content'),
        'resolution_reason': decision['reason'],
        'candidate_rule_uids': decision.get('candidates', []),
        'source_file': source or None,
    }


def export(manifest_path, output_dir):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    inventory = rule_inventory()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = {'source_files': [], 'migrated_files': [], 'status_counts': {}, 'cases': []}
    counts = Counter()
    for name in SOURCE_NAMES:
        source = WORKSPACE / '测试集' / name
        source_hash = sha256(source)
        document = json.loads(source.read_text(encoding='utf-8-sig'))
        audit['source_files'].append({'path': str(source), 'sha256': source_hash})
        for index, case in enumerate(document['cases']):
            case_id = case['case_id']
            decisions = manifest[case_id]
            bindings = [build_binding(case, kind, legacy_id, decisions[kind][legacy_id], inventory)
                        for field, kind in (('must_recall_rule_ids', 'must_recall'),
                                            ('must_not_recall_rule_ids', 'must_not_recall'))
                        for legacy_id in case['expected'].get(field, [])]
            if set(decisions) != {'must_recall', 'must_not_recall'} or any(
                set(decisions[kind]) != set(case['expected'].get(field, []))
                for kind, field in (('must_recall', 'must_recall_rule_ids'),
                                    ('must_not_recall', 'must_not_recall_rule_ids'))):
                raise ValueError(f'{case_id}: manifest expectations differ from source')
            document['cases'][index] = migrate_case(case, bindings, set(inventory))
            counts.update(item['resolution_status'] for item in bindings)
            audit['cases'].append({'case_id': case_id, 'bindings': bindings})
        target = output_dir / name
        target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        audit['migrated_files'].append({'path': str(target), 'sha256': sha256(target)})
        if sha256(source) != source_hash:
            raise RuntimeError(f'source changed during export: {source}')
    audit['status_counts'] = dict(sorted(counts.items()))
    (output_dir / 'uid_migration_audit.json').write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 两份 JSON 测试集 UID 迁移审计', '',
             '原文件未修改。只有 resolved / replace_expected_rule 的内容召回项进入 UID 评分。', '',
             f"状态统计：{json.dumps(audit['status_counts'], ensure_ascii=False)}", '']
    for item in audit['cases']:
        lines += [f"## {item['case_id']}", '', '| 预期 | 旧 ID | 状态 | UID | 现规则/条文 | 理由 |',
                  '|---|---|---|---|---|---|']
        for binding in item['bindings']:
            cells = [binding['expectation_type'], binding['legacy_rule_id'],
                     binding['resolution_status'], binding['rule_uid'] or '—',
                     f"{binding['matched_rule_id'] or '—'} {binding['matched_article_or_locator'] or ''}",
                     binding['resolution_reason']]
            lines.append('| ' + ' | '.join(str(cell).replace('|', '/') for cell in cells) + ' |')
        lines.append('')
    (output_dir / 'uid_migration_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default=str(BASE / 'assets' / 'json_test_uid_bindings_20260917.json'))
    parser.add_argument('--output-dir', default=str(BASE / 'reports' / 'json_test_uid_migration_20260917'))
    args = parser.parse_args()
    result = export(args.manifest, args.output_dir)
    print(json.dumps({'status_counts': result['status_counts'],
                      'migrated_files': result['migrated_files']}, ensure_ascii=False, indent=2))
