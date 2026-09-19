# -*- coding: utf-8 -*-
"""Contracts for the final remaining within-path ranking defects."""

import unittest
from pathlib import Path

from issue_tree_rule_selector import select_issue_tree_rules
from kg_rule_store import load_rule_library
from legal_issue_groups import load_legal_issue_groups


BASE = Path(__file__).resolve().parents[1]


class RemainingEndorsementRankingAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rules = load_rule_library(BASE)["data"]["rules"]
        cls.rules = {rule["rule_uid"]: rule for rule in rules}
        cls.groups = load_legal_issue_groups(BASE)

    def test_remaining_health_food_targets_have_specific_scope_and_regex(self):
        for uid in (
            "RUID-d79610014e487328",
            "RUID-92f0e76f37a2a1a1",
            "RUID-c2426548e3dec9be",
            "RUID-d65bef32d08d3476",
        ):
            with self.subTest(rule_uid=uid):
                rule = self.rules[uid]
                self.assertIn(
                    "保健食品",
                    (rule.get("applies_to") or {}).get("product_categories") or [],
                )
                signals = ((rule.get("detection") or {}).get("keyword_signals") or {})
                self.assertTrue(signals.get("regex"))

    def test_pesticide_article_21_rules_do_not_claim_health_food_scope(self):
        for uid in ("RUID-168081152ac6fa9d", "RUID-c72e79162ac67670"):
            with self.subTest(rule_uid=uid):
                rule = self.rules[uid]
                applies_to = rule.get("applies_to") or {}
                self.assertNotIn("保健食品", applies_to.get("industries") or [])
                self.assertNotIn(
                    "保健食品", applies_to.get("product_categories") or []
                )

    def test_article_18_endorser_duplicates_have_reviewed_representative(self):
        groups = {
            group["issue_group_id"]: group
            for group in self.groups.get("groups") or []
        }
        group = groups["health_food_ad_law_article_18_endorser"]
        self.assertEqual("RUID-d79610014e487328", group["preferred_rule_uid"])
        self.assertEqual(
            {
                "RUID-02f4d529f6d0383c",
                "RUID-d58a892d4bc0c4ac",
                "RUID-d79610014e487328",
            },
            set(group["member_rule_uids"]),
        )
        platform_group = groups["xiaohongshu_health_food_endorser"]
        self.assertEqual(
            {"RUID-581e6b801073e750", "RUID-545f9ad8dd6797c1"},
            set(platform_group["member_rule_uids"]),
        )

    def _select(self, issue_id, candidate_uids, material_text):
        expansion = {
            "direct_rule_uids": candidate_uids,
            "fact_check_rule_uids": [],
            "supporting_rule_uids": [],
            "proactive_check_rule_uids": [],
            "exception_rule_uids": [],
            "trace": [
                {
                    "issue_id": issue_id,
                    "mapping_type": "direct",
                    "canonical_rule_uid": uid,
                }
                for uid in candidate_uids
            ],
        }
        return select_issue_tree_rules(
            expansion,
            [{"level_3_issue_id": issue_id}],
            {uid: self.rules[uid] for uid in candidate_uids},
            {
                "context": {
                    "industry": "保健食品",
                    "platforms": ["抖音", "小红书"],
                    "product_category": "营养补充",
                    "material_type": "直播话术",
                }
            },
            {"material_text": material_text},
            self.groups,
            semantic_scorer=lambda *args, **kwargs: {
                uid: {"semantic_score": 0.99 - index / 100}
                for index, uid in enumerate(candidate_uids)
            },
            per_path_limit=3,
            direct_limit=6,
        )

    def test_reviewed_endorser_rule_reaches_category_path_top_three(self):
        result = self._select(
            "ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY",
            [
                "RUID-581e6b801073e750",
                "RUID-545f9ad8dd6797c1",
                "RUID-07c06c5e0785bdbc",
                "RUID-02f4d529f6d0383c",
                "RUID-d58a892d4bc0c4ac",
                "RUID-d79610014e487328",
            ],
            "中国营养学会专家亲测推荐，权威科研机构认证。",
        )
        self.assertIn("RUID-d79610014e487328", result["selected_direct_rule_uids"])

    def test_health_food_expert_rule_beats_mis_scoped_pesticide_rule(self):
        result = self._select(
            "ENDORSEMENT.PROHIBITED_SUBJECT",
            ["RUID-168081152ac6fa9d", "RUID-92f0e76f37a2a1a1"],
            "中国营养学会专家亲测推荐。",
        )
        self.assertEqual(
            ["RUID-92f0e76f37a2a1a1"],
            result["selected_direct_rule_uids"][:1],
        )


if __name__ == "__main__":
    unittest.main()
