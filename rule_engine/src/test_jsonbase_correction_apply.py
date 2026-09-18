# -*- coding: utf-8 -*-
import shutil
import sys
import tempfile
import unittest
import hashlib
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jsonbase_correction_migration import apply_manifest, inventory_rules, load_manifest
from test_jsonbase_correction_migration import SIDE_PATH_UIDS, SOURCE_REPAIR_UIDS
from jsonbase_correction_migration import write_migration_artifacts
from correction_test_fixture import copy_frozen_jsonbase


MANIFEST = ROOT / "assets" / "jsonbase_correction_manifest_20260917.json"


ROLE_EXPECTATIONS = {
    'RUID-5918828973a76530': ('direct', ['direct']),
    'RUID-11072b7051c09786': ('supporting_basis', ['supporting_basis']),
    'RUID-5aa5c8f2aa831518': ('supporting_basis', ['supporting_basis']),
    'RUID-6003a44f5ad562ab': ('supporting_basis', ['supporting_basis']),
    'RUID-4a6d2c4fc4cc871e': ('supporting_basis', ['supporting_basis']),
    'RUID-444e62477f0779b1': ('supporting_basis', ['supporting_basis']),
    'RUID-ec56d205b19873b0': ('proactive_check', ['proactive_check']),
    'RUID-60197dfa6e387977': ('proactive_check', ['proactive_check']),
    'RUID-ba33920c2d3dd6a9': ('proactive_check', ['proactive_check']),
    'RUID-b288979a746ecc79': ('direct', ['direct', 'fact_check']),
    'RUID-fba2b7c4e349d1ee': ('proactive_check', ['proactive_check', 'fact_check']),
}

PLATFORM_EXPECTATIONS = {
    'RUID-8a102844838a7107': ['B\u7ad9'],
    'RUID-0aa92e46809d6596': ['B\u7ad9'],
    'RUID-fe1de6c6adfa8d2f': ['B\u7ad9'],
    'RUID-7d0cafae98e5c7f3': ['\u5c0f\u7ea2\u4e66'],
    'RUID-60197dfa6e387977': ['\u5c0f\u7ea2\u4e66'],
    'RUID-ba33920c2d3dd6a9': ['\u5c0f\u7ea2\u4e66'],
    'RUID-2d6b54805a05b56a': ['\u5c0f\u7ea2\u4e66'],
    'RUID-e255eaff8d3be92b': ['\u6dd8\u5b9d'],
}


class JsonbaseCorrectionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jsonbase = Path(self.temp.name) / 'jsonbase'
        copy_frozen_jsonbase(ROOT, self.jsonbase)

    def tearDown(self):
        self.temp.cleanup()

    def test_roles_and_platform_scopes_follow_approved_contract(self):
        apply_manifest(self.jsonbase, MANIFEST, write=True)
        rules = {uid: rows[0]['rule'] for uid, rows in inventory_rules(self.jsonbase).items()}
        for uid, (primary_role, roles) in ROLE_EXPECTATIONS.items():
            self.assertEqual(primary_role, rules[uid]['review_role'], uid)
            self.assertEqual(roles, rules[uid]['review_roles'], uid)
        for uid, platforms in PLATFORM_EXPECTATIONS.items():
            self.assertEqual(platforms, rules[uid]['applies_to']['platforms'], uid)
            self.assertEqual('exact', rules[uid]['platform_gate'], uid)

    def test_dry_run_does_not_write_any_jsonbase_file(self):
        before = {
            path.relative_to(self.jsonbase): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.jsonbase.rglob('*.json')
        }
        report = apply_manifest(self.jsonbase, MANIFEST, write=False)
        after = {
            path.relative_to(self.jsonbase): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.jsonbase.rglob('*.json')
        }
        self.assertGreater(report['changed_rule_count'], 0)
        self.assertEqual(before, after)

    def test_all_side_path_records_have_old_value_protection(self):
        import json
        import jsonbase_correction_migration as migration
        uid = next(iter(SIDE_PATH_UIDS))
        row = inventory_rules(self.jsonbase)[uid][0]
        payload = json.loads(row['path'].read_text(encoding='utf-8'))
        for rule in migration._walk_rule_records(payload):
            if rule.get('rule_uid') == uid:
                rule['title'] = 'unexpected concurrent edit'
        row['path'].write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'old-value mismatch'):
            apply_manifest(self.jsonbase, MANIFEST, write=True)

    def test_non_direct_roles_cannot_recall_or_conclude_as_content(self):
        apply_manifest(self.jsonbase, MANIFEST, write=True)
        rules = {uid: rows[0]['rule'] for uid, rows in inventory_rules(self.jsonbase).items()}
        for uid, (_, roles) in ROLE_EXPECTATIONS.items():
            if 'direct' in roles or 'fact_check' in roles:
                continue
            rule = rules[uid]
            self.assertFalse(rule['direct_conclusion_enabled'], uid)
            for channel in ('keyword_enabled', 'semantic_enabled', 'catalog_recall_enabled'):
                self.assertFalse(rule['recall'][channel], uid)

    def test_unexpected_old_value_aborts_instead_of_overwriting(self):
        row = inventory_rules(self.jsonbase)['RUID-abcddf44be8c7b73'][0]
        path = row['path']
        payload = __import__('json').loads(path.read_text(encoding='utf-8'))
        for rule in __import__('jsonbase_correction_migration')._walk_rule_records(payload):
            if rule.get('rule_uid') == 'RUID-abcddf44be8c7b73':
                rule['applies_to']['industries'] = ['unexpected']
        path.write_text(__import__('json').dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'old-value mismatch'):
            apply_manifest(self.jsonbase, MANIFEST, write=True)


    def test_migration_artifacts_include_uid_redirect_and_report(self):
        report = apply_manifest(self.jsonbase, MANIFEST, write=False)
        self.assertEqual(set(report['changed_files']), set(report['file_hashes_before']))
        self.assertEqual(set(report['changed_files']), set(report['file_hashes_after']))
        self.assertNotEqual(report['file_hashes_before'], report['file_hashes_after'])
        artifact_root = Path(self.temp.name) / 'artifact_root'
        paths = write_migration_artifacts(artifact_root, report, MANIFEST)
        redirect = __import__('json').loads(paths['uid_redirects'].read_text(encoding='utf-8'))
        saved_report = __import__('json').loads(paths['migration_report'].read_text(encoding='utf-8'))
        self.assertEqual(
            'RUID-97c034528fab40c3',
            redirect['redirects']['RUID-c8d9714e6134eb2e'],
        )
        self.assertEqual(report['changed_uids'], saved_report['changed_uids'])


class JsonbaseCorrectionApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.jsonbase = Path(self.temp.name) / "jsonbase"
        copy_frozen_jsonbase(ROOT, self.jsonbase)

    def tearDown(self):
        self.temp.cleanup()

    def test_apply_is_idempotent_and_enforces_governance(self):
        first = apply_manifest(self.jsonbase, MANIFEST, write=True)
        second = apply_manifest(self.jsonbase, MANIFEST, write=True)
        self.assertGreater(first["changed_rule_count"], 0)
        self.assertEqual(0, second["changed_rule_count"])
        rules = {uid: rows[0]["rule"] for uid, rows in inventory_rules(self.jsonbase).items()}
        for uid in SIDE_PATH_UIDS:
            rule = rules[uid]
            self.assertEqual("workflow", rule["recall"]["trigger_layer"], uid)
            self.assertFalse(rule["recall"]["keyword_enabled"], uid)
            self.assertFalse(rule["recall"]["semantic_enabled"], uid)
            self.assertFalse(rule["recall"]["catalog_recall_enabled"], uid)
            self.assertFalse(rule["direct_conclusion_enabled"], uid)
        for uid in SOURCE_REPAIR_UIDS:
            rule = rules[uid]
            self.assertEqual("verified", rule["source_repair"]["status"], uid)
            self.assertGreater(len(rule["legal_basis"][0]["text"]), 20, uid)

    def test_duplicate_source_redirect_and_scope_fixes(self):
        apply_manifest(self.jsonbase, MANIFEST, write=True)
        rules = {uid: rows[0]["rule"] for uid, rows in inventory_rules(self.jsonbase).items()}
        duplicate = rules["RUID-c8d9714e6134eb2e"]
        self.assertEqual("duplicate_source", duplicate["asset_disposition"])
        self.assertEqual("RUID-97c034528fab40c3", duplicate["canonical_rule_uid"])
        self.assertFalse(duplicate["direct_conclusion_enabled"])
        for uid in ("RUID-abcddf44be8c7b73", "RUID-4a6d2c4fc4cc871e"):
            self.assertEqual(["通用"], rules[uid]["applies_to"]["industries"])


if __name__ == "__main__":
    unittest.main()
