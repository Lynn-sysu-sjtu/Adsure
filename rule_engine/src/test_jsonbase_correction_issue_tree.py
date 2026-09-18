import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
from apply_approved_issue_tree_v02 import build_approved_assets
from jsonbase_correction_migration import load_manifest


class CorrectionIssueTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_approved_assets(SRC.parent)
        cls.rows = cls.result['mappings']['mappings']
        cls.nodes = {n['issue_id'] for n in cls.result['taxonomy']['nodes']}

    def test_disparagement_has_one_node_and_correct_roles(self):
        old = 'PROHIBITED_CONTENT.PROHIBITED_PRODUCTS.ADVERTISING_DISPARAGEMENT'
        self.assertNotIn(old, self.nodes)
        direct = [r for r in self.rows if r['rule_uid'] == 'RUID-5918828973a76530']
        basis = [r for r in self.rows if r['rule_uid'] == 'RUID-11072b7051c09786']
        self.assertTrue(direct and basis)
        self.assertEqual({r['issue_id'] for r in direct}, {r['issue_id'] for r in basis})
        self.assertTrue(all(r['mapping_type'] == 'direct' for r in direct))
        self.assertTrue(all(r['mapping_type'] == 'supporting_basis' for r in basis))

    def test_duplicate_and_workflow_uids_are_not_active_mappings(self):
        manifest = load_manifest(SRC.parent / 'assets/jsonbase_correction_manifest_20260917.json')
        banned = {e['rule_uid'] for e in manifest['rules'] if e['action'] in ('side_path', 'duplicate_source')}
        self.assertFalse(banned & {r['rule_uid'] for r in self.rows})

    def test_qualification_and_label_rules_move_to_correct_nodes(self):
        expected = {
            'RUID-60197dfa6e387977': 'EVIDENCE_FACT.QUALIFICATION_FILING.PRODUCT_QUALIFICATION_MATERIAL_INCOMPLETE_OR_INCONSISTENT',
            'RUID-ba33920c2d3dd6a9': 'EVIDENCE_FACT.QUALIFICATION_FILING.PRODUCT_QUALIFICATION_MATERIAL_INCOMPLETE_OR_INCONSISTENT',
            'RUID-ec56d205b19873b0': 'DISCLOSURE_WARNING.LABEL_SOURCE.LABEL_MANDATORY_INFO_MISSING',
            'RUID-eb5568dc49e51df9': 'EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.HEALTH_FOOD_FUNCTION_CLAIM_NONCOMPLIANT',
        }
        for uid, issue in expected.items():
            rows = [r for r in self.rows if r['rule_uid'] == uid]
            self.assertTrue(rows, uid)
            self.assertEqual({issue}, {r['issue_id'] for r in rows}, uid)


if __name__ == '__main__':
    unittest.main()
