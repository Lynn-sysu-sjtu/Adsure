# -*- coding: utf-8 -*-
import copy
import json
import tempfile
import unittest
from pathlib import Path

from apply_health_keyword_pilot import PILOT_KEYWORDS, apply_keyword_pilot


class ApplyHealthKeywordPilotTest(unittest.TestCase):
    def _fixture(self, root):
        rules = []
        for uid, config in PILOT_KEYWORDS.items():
            rules.append({
                'rule_uid': uid,
                'rule_id': config['rule_id'],
                'detection': {
                    'keyword_signals': {
                        'hit_terms': list(config['old_hit_terms']),
                        'regex': [],
                        'context_signals': [],
                        'negative_signals': [],
                    },
                },
            })
        rules.append({
            'rule_uid': 'RUID-untouched',
            'rule_id': 'OTHER',
            'detection': {'keyword_signals': {'hit_terms': ['保持不变']}},
        })
        path = root / '保健食品' / 'rules.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'rules': rules}, ensure_ascii=False), encoding='utf-8')
        return path

    def test_appends_only_approved_terms_and_preserves_other_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            before_other = copy.deepcopy(json.loads(path.read_text(encoding='utf-8'))['rules'][-1])
            audit = apply_keyword_pilot(root)
            rules = json.loads(path.read_text(encoding='utf-8'))['rules']

        by_uid = {rule['rule_uid']: rule for rule in rules}
        self.assertEqual(set(PILOT_KEYWORDS), set(audit['changed_rule_uids']))
        for uid, config in PILOT_KEYWORDS.items():
            terms = by_uid[uid]['detection']['keyword_signals']['hit_terms']
            expected = list(dict.fromkeys(config['old_hit_terms'] + config['added_hit_terms']))
            self.assertEqual(expected, terms)
            self.assertEqual(len(terms), len(set(terms)))
        self.assertEqual(before_other, by_uid['RUID-untouched'])

    def test_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            apply_keyword_pilot(root)
            first_bytes = path.read_bytes()
            audit = apply_keyword_pilot(root)
            self.assertEqual(first_bytes, path.read_bytes())
        self.assertEqual([], audit['changed_rule_uids'])
        self.assertEqual([], audit['changed_files'])

    def test_rejects_unexpected_old_terms_before_writing_any_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['rules'][0]['detection']['keyword_signals']['hit_terms'].append('未批准旧词')
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'precondition'):
                apply_keyword_pilot(root)
            self.assertEqual(before, path.read_bytes())

    def test_rejects_missing_or_duplicate_target_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['rules'].append(copy.deepcopy(payload['rules'][0]))
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'unique'):
                apply_keyword_pilot(root)


if __name__ == '__main__':
    unittest.main()
