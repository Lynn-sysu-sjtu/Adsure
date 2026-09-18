# -*- coding: utf-8 -*-
import unittest

from run_json_uid_baseline import score_uid_results


class JSONUIDBaselineTest(unittest.TestCase):
    def test_only_explicit_uid_targets_enter_recall_denominator(self):
        cases = [
            {'case_id': 'A', 'expected': {'must_recall_rule_ids': ['wrong'],
              'must_recall_rule_uids': ['RUID-right'], 'must_not_recall_rule_uids': [],
              'expected_rule_bindings': [{'resolution_status': 'resolved'}]},
             'diagnostics': {'candidate_rule_uids': ['RUID-wrong'], 'candidate_rule_ids': ['wrong']},
             'actual_response': {'code': 0, 'data': {'matched_rules': []}}},
            {'case_id': 'B', 'expected': {'must_recall_rule_ids': ['old'],
              'must_recall_rule_uids': [], 'must_not_recall_rule_uids': [],
              'expected_rule_bindings': [{'resolution_status': 'unresolved'}]},
             'diagnostics': {'candidate_rule_ids': ['old']},
             'actual_response': {'code': 0, 'data': {'matched_rules': []}}},
        ]
        result = score_uid_results(cases)
        self.assertEqual(result['summary']['positive_case_denominator'], 1)
        self.assertEqual(result['summary']['candidate_all_required_hit'], 0)
        self.assertEqual(result['summary']['unresolved_expectation_count'], 1)
        self.assertEqual(result['cases'][1]['scoring_status'], 'unscorable_no_uid_target')
