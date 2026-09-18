# -*- coding: utf-8 -*-
import json
import unittest
from pathlib import Path

from field_mapper import map_feishu_payload
from kg_rule_store import load_rule_library
from rule_engine import recall_rules


BASE = Path(__file__).resolve().parents[1]
HEALTH_CASES = BASE / 'reports' / 'json_test_uid_migration_20260917' / '20260906保健食品测试样例集.json'
EXPECTED_TARGETS = {
    'HF-AD-003': 'RUID-d79610014e487328',
    'HF-AD-005': 'RUID-4d7b4ffb626c816b',
    'HF-AD-006': 'RUID-4d7b4ffb626c816b',
    'HF-AD-007': 'RUID-4d7b4ffb626c816b',
}


class HealthKeywordPilotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rule_library(BASE)['data']['rules']
        document = json.loads(HEALTH_CASES.read_text(encoding='utf-8'))
        cls.cases = {case['case_id']: case for case in document['cases']}

    def _keyword_uids(self, case_id):
        request = map_feishu_payload(self.cases[case_id]['input_payload'])
        recalled = recall_rules(self.rules, request, context_package=None, keyword_limit=8)
        return {rule.get('rule_uid') for rule, _ in recalled}

    def test_target_uids_survive_the_real_keyword_top8(self):
        for case_id, target_uid in EXPECTED_TARGETS.items():
            with self.subTest(case_id=case_id):
                self.assertIn(target_uid, self._keyword_uids(case_id))

    def test_negative_controls_do_not_recall_pilot_uids(self):
        pilot_uids = set(EXPECTED_TARGETS.values())
        for case_id in ('HF-AD-009', 'HF-AD-010'):
            with self.subTest(case_id=case_id):
                self.assertTrue(pilot_uids.isdisjoint(self._keyword_uids(case_id)))


if __name__ == '__main__':
    unittest.main()
