import json
import shutil
import tempfile
import unittest
from pathlib import Path

from apply_approved_issue_tree_v02 import build_approved_assets
import jsonbase_correction_issue_tree as correction

ROOT = Path(__file__).resolve().parents[1]


class FinalCorrectionAssetTests(unittest.TestCase):
    def test_every_excluded_mapping_has_exportable_reason(self):
        result = build_approved_assets(ROOT)
        self.assertTrue(result['mappings']['excluded_mappings'])
        for row in result['mappings']['excluded_mappings']:
            self.assertTrue(row.get('exclusion_role'), row.get('rule_uid'))
            self.assertTrue(row.get('exclusion_reason'), row.get('rule_uid'))

    def test_special_efficacy_is_merged_with_scope_condition_preserved(self):
        result = build_approved_assets(ROOT)
        old = 'EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_SPECIAL_EFFICACY_CLAIM_BY_ORDINARY_PRODUCT'
        target = 'EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_EFFICACY_CLAIM_NONCOMPLIANT'
        self.assertNotIn(old, {n['issue_id'] for n in result['taxonomy']['nodes']})
        rows = [r for r in result['mappings']['mappings'] if r['rule_uid'] == 'RUID-6c252218419f6fb3']
        self.assertTrue(rows)
        self.assertEqual({target}, {r['issue_id'] for r in rows})
        self.assertTrue(all(r.get('scope_condition') == 'ordinary_product_special_efficacy' for r in rows))

    def test_all_deleted_nodes_have_traceable_resolution(self):
        result = build_approved_assets(ROOT)
        nodes = {n['issue_id'] for n in result['taxonomy']['nodes']}
        resolutions = result['taxonomy'].get('issue_resolutions', {})
        for old in (
            'CLAIM_EXPRESSION.AMBIGUOUS_EXAGGERATED.INSTANT_EFFECT_EXAGGERATION',
            'DISCLOSURE_WARNING.CONDITIONS_LIMITS.COSMETIC_EFFICACY_EXEMPTION_SCOPE',
            'DISCLOSURE_WARNING.STATUTORY_WARNING.STATUTORY_DISCLOSURE_NOT_PROMINENT_OR_CLEAR',
            'ENDORSEMENT.JOINT_LIABILITY',
            'ENDORSEMENT.JOINT_LIABILITY.FALSE_AD_JOINT_LIABILITY',
            'WORKFLOW_DUTY.POST_LAUNCH_FULFILLMENT.FALSE_AD_CIVIL_LIABILITY',
            'WORKFLOW_DUTY.PRE_REVIEW',
        ):
            self.assertNotIn(old, nodes)
            self.assertIn(old, resolutions)
            self.assertTrue(set(resolutions[old]['targets']) <= nodes)

    def test_final_export_preserves_schema_and_is_repeatable(self):
        self.assertTrue(hasattr(correction, 'write_final_assets'), 'Final asset exporter missing')
        result = build_approved_assets(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'assets').mkdir()
            for name in ('legal_issue_taxonomy_draft_v0.3.json', 'rule_issue_mapping_draft_v0.3.json'):
                shutil.copy2(ROOT / 'assets' / name, base / 'assets' / name)
            correction.write_final_assets(result, base)
            first = {p.relative_to(base): p.read_bytes() for p in base.rglob('*.json')}
            correction.write_final_assets(result, base)
            second = {p.relative_to(base): p.read_bytes() for p in base.rglob('*.json')}
            self.assertEqual(first, second)
            taxonomy = json.loads((base / 'assets/legal_issue_taxonomy_draft_v0.3.json').read_text(encoding='utf-8'))
            mappings = json.loads((base / 'assets/rule_issue_mapping_draft_v0.3.json').read_text(encoding='utf-8'))
            ids = {n['issue_id'] for n in taxonomy['issues']}
            self.assertEqual(ids, {n['issue_id'] for n in result['taxonomy']['nodes']})
            self.assertTrue(taxonomy.get('source_hashes'))
            for row in mappings['mappings']:
                self.assertIn(row['primary_issue_id'], ids)
                self.assertTrue(set(row['secondary_issue_ids']) <= ids)
                self.assertNotEqual('RUID-c8d9714e6134eb2e', row['rule_uid'])
            self.assertEqual('RUID-97c034528fab40c3', mappings['uid_redirects']['RUID-c8d9714e6134eb2e'])


if __name__ == '__main__':
    unittest.main()
