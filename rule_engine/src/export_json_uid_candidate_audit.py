# -*- coding: utf-8 -*-
"""List all same-ID current-rule candidates behind each migration decision."""

import json
from collections import defaultdict
from pathlib import Path

from json_test_uid_migration import BASE, rule_inventory


def main():
    report_dir = BASE / 'reports' / 'json_test_uid_migration_20260917'
    audit = json.loads((report_dir / 'uid_migration_audit.json').read_text(encoding='utf-8'))
    by_id = defaultdict(list)
    for uid, record in rule_inventory().items():
        rule = record['rule']
        by_id[rule.get('rule_id')].append({
            'rule_uid': uid, 'title': rule.get('title'),
            'source_file': record['source_file'],
            'provisions': [{'article': item.get('article'), 'text': (item.get('text') or '')[:180]}
                           for item in rule.get('legal_basis', []) if isinstance(item, dict)],
        })
    rows = []
    for case in audit['cases']:
        for binding in case['bindings']:
            candidates = by_id[binding['legacy_rule_id']]
            rows.append({'case_id': case['case_id'], 'expectation_type': binding['expectation_type'],
                         'legacy_rule_id': binding['legacy_rule_id'],
                         'selected_rule_uid': binding['rule_uid'],
                         'resolution_status': binding['resolution_status'],
                         'same_id_candidates': candidates,
                         'reason': binding['resolution_reason']})
    path = report_dir / 'uid_candidate_inventory.json'
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'candidate_inventory={path} bindings={len(rows)}')


if __name__ == '__main__':
    main()
