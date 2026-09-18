# -*- coding: utf-8 -*-
import copy
import json
import tempfile
import unittest
from pathlib import Path

from apply_health_vector_pilot import PILOT_RULES, apply_pilot


class HealthVectorPilotTest(unittest.TestCase):
    def _write_fixture(self, root, first_text=None):
        rules = []
        for uid, config in PILOT_RULES.items():
            rules.append({
                'rule_uid': uid,
                'rule_id': config['rule_id'],
                'title': uid,
                'recall': {
                    'vector_text': first_text if first_text is not None and not rules else config['old_vector_text'],
                    'semantic_enabled': True,
                    'semantic_role': 'fallback',
                },
            })
        rules.append({'rule_uid': 'RUID-untouched', 'rule_id': 'OTHER',
                      'recall': {'vector_text': 'do not change'}})
        path = root / '保健食品' / 'rules.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'rules': rules}, ensure_ascii=False), encoding='utf-8')
        return path

    def test_applies_four_approved_scenarios_without_changing_other_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_fixture(root)
            before = json.loads(path.read_text(encoding='utf-8'))['rules'][-1]
            audit = apply_pilot(root)
            rules = json.loads(path.read_text(encoding='utf-8'))['rules']
        by_uid = {rule['rule_uid']: rule for rule in rules}
        self.assertEqual({'RUID-4d7b4ffb626c816b', 'RUID-d79610014e487328'},
                         set(audit['changed_rule_uids']))
        for uid, config in PILOT_RULES.items():
            self.assertEqual(config['scenarios'], by_uid[uid]['recall']['semantic_scenarios'])
            self.assertEqual('fallback', by_uid[uid]['recall']['semantic_role'])
        self.assertEqual(before, by_uid['RUID-untouched'])

    def test_rejects_unexpected_existing_text_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_fixture(root, first_text='unexpected')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'precondition'):
                apply_pilot(root)
            self.assertEqual(before, path.read_bytes())

    def test_rejects_missing_or_duplicate_target_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_fixture(root)
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['rules'].append(copy.deepcopy(payload['rules'][0]))
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'unique'):
                apply_pilot(root)


if __name__ == '__main__':
    unittest.main()
