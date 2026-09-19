# -*- coding: utf-8 -*-
"""Asset and behavior contracts for remaining health-food ranking fixes."""

import unittest
from pathlib import Path

from issue_tree_rule_selector import select_issue_tree_rules
from kg_rule_store import load_rule_library
from legal_issue_groups import load_legal_issue_groups


BASE = Path(__file__).resolve().parents[1]
HEALTH_FOOD_TARGET_UIDS = {
    "RUID-d65bef32d08d3476",
    "RUID-b2af3e129ef8e342",
    "RUID-79f7ff14a5af24ee",
    "RUID-4d7b4ffb626c816b",
}


class RemainingRankingAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rules = load_rule_library(BASE)["data"]["rules"]
        cls.rules = {rule["rule_uid"]: rule for rule in rules}
        cls.legal_issue_groups = load_legal_issue_groups(BASE)

    def test_health_food_target_rules_declare_industry_scope(self):
        for uid in HEALTH_FOOD_TARGET_UIDS:
            with self.subTest(rule_uid=uid):
                industries = set(
                    (self.rules[uid].get("applies_to") or {}).get("industries") or []
                )
                self.assertIn("保健食品", industries)

    def test_health_food_target_rules_declare_product_scope_and_strong_evidence(self):
        for uid in HEALTH_FOOD_TARGET_UIDS:
            with self.subTest(rule_uid=uid):
                applies_to = self.rules[uid].get("applies_to") or {}
                self.assertIn("保健食品", applies_to.get("product_categories") or [])
                signals = ((self.rules[uid].get("detection") or {}).get(
                    "keyword_signals"
                ) or {})
                self.assertTrue(signals.get("regex"))

    def test_exact_duplicate_health_food_rules_have_reviewed_representatives(self):
        groups = {
            group["issue_group_id"]: group
            for group in self.legal_issue_groups.get("groups") or []
        }
        expected = {
            "health_food_ad_law_article_17_treatment": (
                "RUID-1e455acefad683e3",
                {
                    "RUID-1e455acefad683e3",
                    "RUID-10ea14b945299036",
                    "RUID-d65bef32d08d3476",
                },
            ),
            "health_food_ad_law_article_18_disease": (
                "RUID-b2af3e129ef8e342",
                {
                    "RUID-165591db82effab3",
                    "RUID-7704214ffc5d9535",
                    "RUID-b2af3e129ef8e342",
                },
            ),
            "health_food_ad_law_article_18_guarantee": (
                "RUID-4d7b4ffb626c816b",
                {
                    "RUID-3282b7e7f6fc4f3e",
                    "RUID-4d7b4ffb626c816b",
                    "RUID-e9afbede10e31c92",
                },
            ),
        }
        for group_id, (preferred_uid, member_uids) in expected.items():
            with self.subTest(issue_group_id=group_id):
                self.assertIn(group_id, groups)
                self.assertEqual(preferred_uid, groups[group_id].get("preferred_rule_uid"))
                self.assertEqual(member_uids, set(groups[group_id]["member_rule_uids"]))
        self.assertEqual(
            {"保健食品": "RUID-d65bef32d08d3476"},
            groups["health_food_ad_law_article_17_treatment"].get(
                "preferred_rule_uids_by_industry"
            ),
        )

    def test_industry_specific_rules_fill_path_top_three_before_generic_rule(self):
        issue_id = (
            "EFFICACY_PERFORMANCE.DISEASE_MEDICAL."
            "DISEASE_TREATMENT_MEDICAL_CLAIM"
        )
        target_uids = [
            "RUID-d65bef32d08d3476",
            "RUID-b2af3e129ef8e342",
            "RUID-79f7ff14a5af24ee",
        ]
        rules = {uid: self.rules[uid] for uid in target_uids}
        generic_uid = "RUID-generic-medical-test"
        rules[generic_uid] = {
            "rule_uid": generic_uid,
            "source_type": "法规",
            "detection": {
                "keyword_signals": {"hit_terms": ["糖尿病"]},
            },
        }
        expansion = {
            "direct_rule_uids": target_uids + [generic_uid],
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
                for uid in target_uids + [generic_uid]
            ],
        }
        result = select_issue_tree_rules(
            expansion,
            [{"level_3_issue_id": issue_id}],
            rules,
            {"context": {"industry": "保健食品"}},
            {"material_text": "宣称治疗糖尿病并降低血糖"},
            {"groups": []},
            semantic_scorer=lambda *args, **kwargs: {
                generic_uid: {"semantic_score": 0.99},
                target_uids[0]: {"semantic_score": 0.30},
                target_uids[1]: {"semantic_score": 0.20},
                target_uids[2]: {"semantic_score": 0.10},
            },
            per_path_limit=3,
            direct_limit=6,
        )
        self.assertEqual(set(target_uids), set(result["selected_direct_rule_uids"]))

    def test_article_17_group_uses_general_uid_outside_health_food(self):
        issue_id = (
            "EFFICACY_PERFORMANCE.DISEASE_MEDICAL."
            "DISEASE_TREATMENT_MEDICAL_CLAIM"
        )
        candidate_uids = [
            "RUID-1e455acefad683e3",
            "RUID-10ea14b945299036",
            "RUID-d65bef32d08d3476",
        ]
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
        result = select_issue_tree_rules(
            expansion,
            [{"level_3_issue_id": issue_id}],
            {uid: self.rules[uid] for uid in candidate_uids},
            {
                "context": {
                    "industry": "美妆",
                    "platforms": ["小红书"],
                    "product_category": "护肤",
                    "material_type": "图文",
                }
            },
            {"material_text": "宣称可以治疗皮肤疾病。"},
            self.legal_issue_groups,
            semantic_scorer=lambda *args, **kwargs: {},
            per_path_limit=3,
            direct_limit=6,
        )
        self.assertEqual(
            ["RUID-1e455acefad683e3"],
            result["selected_direct_rule_uids"],
        )

    def test_reviewed_duplicate_collapse_leaves_three_distinct_disease_rules(self):
        issue_id = (
            "EFFICACY_PERFORMANCE.DISEASE_MEDICAL."
            "DISEASE_TREATMENT_MEDICAL_CLAIM"
        )
        candidate_uids = [
            "RUID-1e455acefad683e3",
            "RUID-10ea14b945299036",
            "RUID-d65bef32d08d3476",
            "RUID-165591db82effab3",
            "RUID-7704214ffc5d9535",
            "RUID-b2af3e129ef8e342",
            "RUID-cf387407d6592cbf",
            "RUID-66bef2fb5e73c17a",
            "RUID-79f7ff14a5af24ee",
            "RUID-4eb2d27878eedc20",
        ]
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
        semantic_scores = {
            uid: {"semantic_score": 0.99 - index / 100}
            for index, uid in enumerate(candidate_uids)
        }
        result = select_issue_tree_rules(
            expansion,
            [{"level_3_issue_id": issue_id}],
            {uid: self.rules[uid] for uid in candidate_uids},
            {
                "context": {
                    "industry": "保健食品",
                    "platforms": ["抖音"],
                    "product_category": "营养补充",
                    "material_type": "图文",
                }
            },
            {"material_text": "帮助治疗糖尿病，告别降糖药。"},
            self.legal_issue_groups,
            semantic_scorer=lambda *args, **kwargs: semantic_scores,
            per_path_limit=3,
            direct_limit=6,
        )
        self.assertEqual(
            {
                "RUID-d65bef32d08d3476",
                "RUID-b2af3e129ef8e342",
                "RUID-79f7ff14a5af24ee",
            },
            set(result["selected_direct_rule_uids"]),
        )

    def test_reviewed_guarantee_rule_survives_duplicate_and_broad_candidates(self):
        issue_id = (
            "CLAIM_EXPRESSION.GUARANTEE_COMMITMENT."
            "EFFECT_GUARANTEE_COMMITMENT"
        )
        candidate_uids = [
            "RUID-3282b7e7f6fc4f3e",
            "RUID-4d7b4ffb626c816b",
            "RUID-e9afbede10e31c92",
            "RUID-1b86290f71189ff6",
            "RUID-6a8383c10e696e68",
            "RUID-c2426548e3dec9be",
        ]
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
        result = select_issue_tree_rules(
            expansion,
            [{"level_3_issue_id": issue_id}],
            {uid: self.rules[uid] for uid in candidate_uids},
            {
                "context": {
                    "industry": "保健食品",
                    "platforms": ["小红书"],
                    "product_category": "营养补充",
                    "material_type": "图文",
                }
            },
            {"material_text": "纯天然绝对安全，任何人吃都不会有问题。"},
            self.legal_issue_groups,
            semantic_scorer=lambda *args, **kwargs: {
                uid: {"semantic_score": 0.99 - index / 100}
                for index, uid in enumerate(candidate_uids)
            },
            per_path_limit=3,
            direct_limit=6,
        )
        self.assertIn("RUID-4d7b4ffb626c816b", result["selected_direct_rule_uids"])


if __name__ == "__main__":
    unittest.main()
