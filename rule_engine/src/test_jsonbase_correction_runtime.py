import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidate_governance import govern_candidates
from rule_vector_index import _semantic_rule_records
from rule_engine import recall_rules
from catalog_rule_directory import build_catalog_directory
from semantic_recall import semantic_recall_rules
from rule_scope import platform_scope_matches
from jsonbase_correction_migration import inventory_rules, load_manifest
from copy import deepcopy
from unittest.mock import patch


def sample(**changes):
    rule = {
        'rule_uid': 'RUID-test',
        'rule_id': 'test',
        'recall': {'trigger_layer': 'content', 'semantic_enabled': True, 'vector_text': 'best product'},
        'detection': {'keyword_signals': {'hit_terms': ['best']}},
        'applies_to': {},
    }
    rule.update(changes)
    return rule


class CorrectionRuntimeTests(unittest.TestCase):
    def test_independent_catalog_and_semantic_apis_reject_stale_duplicate_flags(self):
        rule = sample(asset_disposition='duplicate_source')
        rule['recall'].update(catalog_recall_enabled=True, catalog_text='best product', catalog_group='truthfulness')
        request = {'material': {'content': 'best product'}, 'context': {}}
        self.assertEqual([], build_catalog_directory([rule], request))
        with patch.dict('os.environ', {'ADSURE_SEMANTIC_BACKEND': 'local'}):
            self.assertEqual([], semantic_recall_rules([rule], request, {}, threshold=0.0))

    def test_real_workflow_uids_are_absent_from_all_three_channels(self):
        root = Path(__file__).resolve().parents[1]
        inventory = inventory_rules(root / 'jsonbase')
        manifest = load_manifest(root / 'assets/jsonbase_correction_manifest_20260917.json')
        for entry in manifest['rules']:
            if entry['action'] != 'side_path':
                continue
            rule = inventory[entry['rule_uid']][0]['rule']
            request = {'material': {'content': rule.get('title', '')}, 'context': {}}
            self.assertEqual([], recall_rules([rule], request), entry['rule_uid'])
            self.assertEqual([], build_catalog_directory([rule], request), entry['rule_uid'])
            with patch.dict('os.environ', {'ADSURE_SEMANTIC_BACKEND': 'local'}):
                self.assertEqual([], semantic_recall_rules([rule], request, {}, threshold=0.0), entry['rule_uid'])
            self.assertEqual([], govern_candidates([(rule, ['llm_catalog:test'])], request, {}), entry['rule_uid'])

    def test_all_eight_real_platform_rules_require_exact_platform(self):
        root = Path(__file__).resolve().parents[1]
        inventory = inventory_rules(root / 'jsonbase')
        uids = ['RUID-8a102844838a7107', 'RUID-0aa92e46809d6596', 'RUID-fe1de6c6adfa8d2f',
                'RUID-7d0cafae98e5c7f3', 'RUID-60197dfa6e387977', 'RUID-ba33920c2d3dd6a9',
                'RUID-2d6b54805a05b56a', 'RUID-e255eaff8d3be92b']
        for uid in uids:
            rule = inventory[uid][0]['rule']
            expected = rule['applies_to']['platforms']
            self.assertTrue(platform_scope_matches(rule, {'context': {'platforms': expected}}), uid)
            for platforms in ([], ['wrong_platform']):
                request = {'material': {'content': rule.get('title', '')}, 'context': {'platforms': platforms}}
                self.assertFalse(platform_scope_matches(rule, request), uid)
                self.assertEqual([], recall_rules([rule], request), uid)
                self.assertEqual([], build_catalog_directory([rule], request), uid)
                with patch.dict('os.environ', {'ADSURE_SEMANTIC_BACKEND': 'local'}):
                    self.assertEqual([], semantic_recall_rules([rule], request, {}, threshold=0.0), uid)
                self.assertEqual([], govern_candidates([(rule, ['semantic:0.99'])], request, {}), uid)

    def test_duplicate_is_rejected_even_with_stale_recall_flags(self):
        rule = sample(asset_disposition='duplicate_source', canonical_rule_uid='RUID-main')
        for hits in (['best'], ['semantic:0.9'], ['llm_catalog:test']):
            self.assertEqual([], govern_candidates([(rule, hits)], {}, {}))
        self.assertEqual([], _semantic_rule_records([rule]))

    def test_workflow_and_supporting_roles_never_enter_judgment(self):
        for changes in (
            {'recall': {'trigger_layer': 'workflow'}},
            {'review_role': 'supporting_basis', 'review_roles': ['supporting_basis']},
            {'review_role': 'proactive_check', 'review_roles': ['proactive_check']},
        ):
            rule = sample(**changes)
            for hits in (['best'], ['semantic:0.9'], ['llm_catalog:test']):
                self.assertEqual([], govern_candidates([(rule, hits)], {}, {}))

    def test_disabled_keyword_channel_is_not_recalled(self):
        rule = sample(recall={'trigger_layer': 'content', 'keyword_enabled': False, 'semantic_enabled': False})
        request = {'material': {'content': 'best'}, 'context': {}}
        self.assertEqual([], recall_rules([rule], request))


if __name__ == '__main__':
    unittest.main()
