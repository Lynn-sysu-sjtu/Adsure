# -*- coding: utf-8 -*-
"""Contracts for the five-case targeted recall assets."""

import json
import re
import unittest
from pathlib import Path

from kg_rule_store import load_rule_library
from legal_issue_groups import load_legal_issue_groups, legal_issue_group_index


BASE = Path(__file__).resolve().parents[1]
PRE_REVIEW_UIDS = {
    "RUID-b6d85093aac76c45",
    "RUID-1bac53642e0ddd34",
    "RUID-70d3fcec74ce985b",
    "RUID-c759ae9e2b02d013",
    "RUID-f2c9db72fdae932e",
}


class FiveCaseTargetedRecallAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rules = load_rule_library(BASE)["data"]["rules"]
        cls.rules = {rule["rule_uid"]: rule for rule in rules}

    def test_health_food_pre_review_uses_fact_quota_and_preferred_representative(self):
        mapping_path = (
            BASE / "reports" / "approved_issue_tree_v03"
            / "approved_rule_issue_mapping_v0.2.json"
        )
        mappings = json.loads(mapping_path.read_text(encoding="utf-8-sig"))["mappings"]
        target = [item for item in mappings if item.get("rule_uid") in PRE_REVIEW_UIDS]
        self.assertEqual(PRE_REVIEW_UIDS, {item["rule_uid"] for item in target})
        self.assertEqual({"fact_check"}, {item["mapping_type"] for item in target})

        group_index = legal_issue_group_index(load_legal_issue_groups(BASE))
        group = group_index["RUID-b6d85093aac76c45"]
        self.assertTrue(PRE_REVIEW_UIDS.issubset(set(group["member_rule_uids"])))
        self.assertEqual("RUID-b6d85093aac76c45", group["preferred_rule_uid"])

    def test_beauty_safety_guarantee_has_combination_regex(self):
        rule = self.rules["RUID-503970617d0d84f1"]
        patterns = rule["detection"]["keyword_signals"]["regex"]
        text = "食品级儿童润唇膏，宝宝舔了也能吃，100%没有任何风险"
        self.assertTrue(any(re.search(pattern, text) for pattern in patterns))

    def test_target_rules_have_focused_keywords_and_semantic_scenarios(self):
        efficacy = self.rules["RUID-adbdf62e0522296e"]
        efficacy_terms = set(efficacy["detection"]["keyword_signals"]["hit_terms"])
        self.assertTrue({"祛斑", "防晒", "防脱发"}.issubset(efficacy_terms))
        self.assertIn(
            "ordinary_cosmetic_special_efficacy",
            {item["scenario_id"] for item in efficacy["recall"]["semantic_scenarios"]},
        )

        false_ad = self.rules["RUID-d958618a8503a8de"]
        false_terms = set(false_ad["detection"]["keyword_signals"]["hit_terms"])
        self.assertTrue({"前后对比", "使用前", "使用后"}.issubset(false_terms))
        self.assertIn(
            "unverifiable_before_after_effect",
            {item["scenario_id"] for item in false_ad["recall"]["semantic_scenarios"]},
        )

        patent = self.rules["RUID-07fe253c98da8c7b"]
        self.assertFalse(patent["recall"]["semantic_enabled"])
        self.assertIn(
            "patent_claim_without_number_or_type",
            {item["scenario_id"] for item in patent["recall"]["semantic_scenarios"]},
        )

    def test_target_rules_have_expandable_reviewed_issue_paths(self):
        mapping_path = (
            BASE / "reports" / "approved_issue_tree_v03"
            / "approved_rule_issue_mapping_v0.2.json"
        )
        mappings = json.loads(mapping_path.read_text(encoding="utf-8-sig"))["mappings"]
        actual = {
            (item["rule_uid"], item["issue_id"], item["mapping_type"])
            for item in mappings
        }
        expected = {
            (
                "RUID-4aee7195c03d3d3c",
                "EVIDENCE_FACT.QUALIFICATION_FILING.PRODUCT_QUALIFICATION_MATERIAL_INCOMPLETE_OR_INCONSISTENT",
                "fact_check",
            ),
            (
                "RUID-6a53a40ee3899dba",
                "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_SPECIFIC_FACTS",
                "direct",
            ),
            (
                "RUID-d958618a8503a8de",
                "TRUTHFULNESS.MISLEADING_OMISSION.FALSE_ADVERTISING_GENERAL",
                "direct",
            ),
            (
                "RUID-d958618a8503a8de",
                "TRUTHFULNESS.FABRICATED_EFFECT.FABRICATED_EFFECT_GENERAL",
                "direct",
            ),
            (
                "RUID-d958618a8503a8de",
                "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_SPECIFIC_FACTS",
                "direct",
            ),
            (
                "RUID-07fe253c98da8c7b",
                "IP_PERSONALITY.PATENT_AWARD.PATENT_ADVERTISING_MISSING_PATENT_NUMBER_AND_TYPE",
                "fact_check",
            ),
        }
        self.assertTrue(expected.issubset(actual))


if __name__ == "__main__":
    unittest.main()
