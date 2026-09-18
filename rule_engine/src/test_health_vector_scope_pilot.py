# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from apply_health_vector_scope_pilot import OLD_MATERIAL_TYPES, TARGET_UIDS, apply_scope_pilot
from semantic_recall import _rule_filter_reasons


class HealthVectorScopePilotTest(unittest.TestCase):
    def _fixture(self, root):
        rules = []
        for uid in TARGET_UIDS:
            rules.append({
                'rule_uid': uid,
                'rule_id': 'HF-SCOPE',
                'industry': '保健食品',
                'applies_to': {
                    'industries': ['保健食品'],
                    'product_categories': ['保健食品'],
                    'material_types': list(OLD_MATERIAL_TYPES),
                    'platforms': [], 'channels': [], 'audiences': [],
                },
            })
        rules.append({'rule_uid': 'RUID-other', 'applies_to': {'product_categories': ['美妆']}})
        path = root / '保健食品' / 'rules.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'rules': rules}, ensure_ascii=False), encoding='utf-8')
        return path

    def test_scope_accepts_health_subcategories_and_short_video_only_for_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            audit = apply_scope_pilot(root)
            rules = json.loads(path.read_text(encoding='utf-8'))['rules']
        by_uid = {rule['rule_uid']: rule for rule in rules}
        request = {'context': {'industry': '保健食品', 'product_category': '营养补充',
                               'material_type': '短视频脚本', 'platforms': ['小红书']}}
        for uid in TARGET_UIDS:
            self.assertEqual([], _rule_filter_reasons(by_uid[uid], request))
            self.assertEqual([], by_uid[uid]['applies_to']['product_categories'])
            self.assertIn('短视频脚本', by_uid[uid]['applies_to']['material_types'])
            self.assertEqual(['保健食品'], by_uid[uid]['applies_to']['industries'])
        self.assertEqual(['美妆'], by_uid['RUID-other']['applies_to']['product_categories'])
        self.assertEqual(set(TARGET_UIDS), set(audit['changed_rule_uids']))

    def test_scope_still_rejects_other_industries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            apply_scope_pilot(root)
            rule = json.loads(path.read_text(encoding='utf-8'))['rules'][0]
        request = {'context': {'industry': '美妆', 'product_category': '营养补充',
                               'material_type': '短视频脚本', 'platforms': []}}
        self.assertIn('industry_scope_mismatch', _rule_filter_reasons(rule, request))

    def test_rejects_unexpected_scope_precondition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._fixture(root)
            payload = json.loads(path.read_text(encoding='utf-8'))
            payload['rules'][0]['applies_to']['industries'] = ['通用']
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'precondition'):
                apply_scope_pilot(root)
            self.assertEqual(before, path.read_bytes())


if __name__ == '__main__':
    unittest.main()
