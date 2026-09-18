# -*- coding: utf-8 -*-
import copy
import unittest

from json_test_uid_migration import migrate_case, validate_bindings


class UIDMigrationTest(unittest.TestCase):
    def test_resolved_binding_uses_uid_without_changing_legacy_id(self):
        case = {'case_id': 'X', 'expected': {'must_recall_rule_ids': ['OLD']}}
        binding = {'expectation_type': 'must_recall', 'legacy_rule_id': 'OLD',
                   'rule_uid': 'RUID-1', 'resolution_status': 'replace_expected_rule',
                   'matched_rule_id': 'NEW', 'matched_document_title': '广告法',
                   'matched_article_or_locator': '第十七条',
                   'matched_provision_excerpt': '禁止医疗用语',
                   'expected_channel': 'content', 'resolution_reason': '条文一致'}
        original = copy.deepcopy(case)
        result = migrate_case(case, [binding], {'RUID-1'})
        self.assertEqual(case, original)
        self.assertEqual(result['expected']['must_recall_rule_uids'], ['RUID-1'])
        self.assertEqual(result['expected']['must_recall_rule_ids'], ['OLD'])

    def test_unresolved_never_falls_back_to_legacy_id(self):
        case = {'case_id': 'X', 'expected': {'must_recall_rule_ids': ['OLD']}}
        binding = {'expectation_type': 'must_recall', 'legacy_rule_id': 'OLD',
                   'rule_uid': None, 'resolution_status': 'unresolved',
                   'matched_rule_id': None, 'matched_document_title': None,
                   'matched_article_or_locator': None, 'matched_provision_excerpt': None,
                   'expected_channel': 'content', 'resolution_reason': '规则缺失'}
        result = migrate_case(case, [binding], set())
        self.assertEqual(result['expected']['must_recall_rule_uids'], [])
        self.assertEqual(result['expected']['expected_rule_bindings'][0]['resolution_status'], 'unresolved')

    def test_missing_binding_and_nonexistent_uid_are_rejected(self):
        case = {'case_id': 'X', 'expected': {'must_recall_rule_ids': ['OLD']}}
        with self.assertRaisesRegex(ValueError, 'missing'):
            validate_bindings(case, [], set())
        binding = {'expectation_type': 'must_recall', 'legacy_rule_id': 'OLD',
                   'rule_uid': 'RUID-absent', 'resolution_status': 'resolved',
                   'matched_rule_id': 'OLD', 'matched_document_title': '广告法',
                   'matched_article_or_locator': '第十七条',
                   'matched_provision_excerpt': '内容', 'expected_channel': 'content',
                   'resolution_reason': '条文一致'}
        with self.assertRaisesRegex(ValueError, 'unknown UID'):
            validate_bindings(case, [binding], set())
