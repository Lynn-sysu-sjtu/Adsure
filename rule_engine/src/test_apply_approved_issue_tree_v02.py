# -*- coding: utf-8 -*-

import unittest
from pathlib import Path

from apply_approved_issue_tree_v02 import build_approved_assets


ROOT = Path(__file__).resolve().parents[1]


class ApprovedIssueTreeV02Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build_approved_assets(ROOT)
        cls.nodes = {item["issue_id"]: item for item in cls.result["taxonomy"]["nodes"]}
        cls.mappings = cls.result["mappings"]["mappings"]

    def issue_names(self):
        return {item["name"] for item in self.nodes.values()}

    def mapped_issues(self, uid):
        return {item["issue_id"] for item in self.mappings if item["rule_uid"] == uid}

    def test_approved_merges_remove_redundant_issue_nodes(self):
        names = self.issue_names()
        self.assertNotIn("广告内容超出注册或备案范围", names)
        self.assertNotIn("跨类别功效宣称", names)
        self.assertNotIn("广告夸张描述即时效果", names)
        self.assertNotIn("免予公布功效宣称依据摘要的适用范围", names)
        self.assertNotIn("虚假广告中的连带责任", names)
        self.assertNotIn("投放后履约与持续核验", names)

    def test_scope_rules_are_moved_to_correct_issue_families(self):
        self.assertIn(
            "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.SPECIAL_MEDICAL_FOOD_AD_OVER_REGISTERED_SCOPE",
            self.mapped_issues("RUID-1c76c8f71fb25e6a"),
        )
        self.assertIn(
            "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.DRUG_AD_OVER_INSTRUCTION_SCOPE",
            self.mapped_issues("RUID-644b0ca0795e37d0"),
        )
        self.assertIn(
            "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_EFFICACY_CLAIM_NONCOMPLIANT",
            self.mapped_issues("RUID-6c252218419f6fb3"),
        )

    def test_exception_and_supporting_basis_are_not_direct_violations(self):
        exemption = [item for item in self.mappings if item["rule_uid"] == "RUID-0f9e19a6e362072e"]
        self.assertEqual(exemption[0]["mapping_type"], "exception")
        generic = [item for item in self.mappings if item["rule_uid"] == "RUID-6003a44f5ad562ab"]
        self.assertTrue(generic)
        self.assertTrue(all(item["mapping_type"] == "supporting_basis" for item in generic))

    def test_restructured_minors_and_material_directories_exist(self):
        names = self.issue_names()
        for name in (
            "广告定向、发布场所与媒介限制",
            "禁止向未成年人销售或宣传特定商品",
            "未成年人个人信息保护",
            "侮辱诽谤",
            "落地页与跳转规范",
            "广告展示行为与关闭规范",
            "广告位、投放规格与频次",
        ):
            self.assertIn(name, names)
        self.assertNotIn("平台未成年人保护运营义务", names)

    def test_authorization_and_minor_issue_moves_match_approved_review(self):
        self.assertEqual(
            self.nodes["IP_PERSONALITY.THIRD_PARTY_AUTH"]["name"],
            "授权要求",
        )
        insult_id = "MINORS_PUBLIC_ORDER.PUBLIC_MORALITY.DEFAMATION_INSULT"
        access_id = (
            "MINORS_PUBLIC_ORDER.DISCRIMINATION_INSULT."
            "MINOR_ACCESS_RESTRICTION_VIOLATION"
        )
        self.assertIn(insult_id, self.nodes)
        self.assertIn(access_id, self.nodes)
        self.assertNotIn("MINORS_PUBLIC_ORDER.PLATFORM_PROTECTION_DUTY", self.nodes)

        warning_or_live = [
            item for item in self.mappings
            if item["original_issue_id"].endswith(
                ("MINOR_HARMFUL_CONTENT_WARNING", "MINOR_LIVE_STREAM_ACCOUNT_REGISTRATION")
            )
        ]
        access = [
            item for item in self.mappings
            if item["original_issue_id"].endswith("MINOR_ACCESS_RESTRICTION_VIOLATION")
        ]
        self.assertTrue(warning_or_live)
        excluded_access = [
            item for item in self.result['mappings']['excluded_mappings']
            if item['rule_uid'] == 'RUID-a0a3175230952dcd'
        ]
        self.assertFalse(access)
        self.assertTrue(excluded_access)
        self.assertEqual('workflow_reference', excluded_access[0]['exclusion_role'])
        self.assertTrue(all(item["issue_id"] == insult_id for item in warning_or_live))
        self.assertTrue(all(item["issue_id"] == access_id for item in access))

    def test_all_active_mappings_have_source_text(self):
        self.assertGreater(len(self.mappings), 700)
        self.assertTrue(all(item.get("original_text") for item in self.mappings))
        node_ids = set(self.nodes)
        self.assertTrue(all(item["issue_id"] in node_ids for item in self.mappings))


if __name__ == "__main__":
    unittest.main()
