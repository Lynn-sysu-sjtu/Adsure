# -*- coding: utf-8 -*-
import unittest

from run_three_dataset_baseline import compare_json_case


class UIDScoringContractTest(unittest.TestCase):
    def test_explicit_empty_uid_list_does_not_fallback_to_legacy_id(self):
        case = {'expected': {'must_recall_rule_ids': ['OLD'],
                             'must_recall_rule_uids': [], 'must_not_recall_rule_uids': [],
                             'expected_rule_bindings': [{'resolution_status': 'unresolved'}]}}
        comparison = compare_json_case(case, {'code': 0, 'data': {'matched_rules': []}},
                                       {'candidate_rule_ids': []})
        self.assertEqual(comparison['primary_rule_identity'], 'rule_uid')
        self.assertFalse(comparison['expected_rule_recall_scorable'])
        self.assertFalse(comparison['required_candidate_recall_match'])
