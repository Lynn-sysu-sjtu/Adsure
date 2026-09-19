# -*- coding: utf-8 -*-
"""Regression for the final strong-evidence global allocation winner."""

import unittest
from pathlib import Path

from issue_tree_rule_selector import select_issue_tree_rules
from kg_rule_store import load_rule_library
from legal_issue_groups import load_legal_issue_groups


BASE = Path(__file__).resolve().parents[1]
TARGET_UID = "RUID-d958618a8503a8de"


class RemainingGlobalAllocationAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rules = load_rule_library(BASE)["data"]["rules"]
        cls.rules = {rule["rule_uid"]: rule for rule in rules}
        cls.groups = load_legal_issue_groups(BASE)

    def test_general_false_advertising_rule_has_unsubstantiated_effect_regex(self):
        signals = ((self.rules[TARGET_UID].get("detection") or {}).get(
            "keyword_signals"
        ) or {})
        self.assertTrue(signals.get("regex"))

    def test_strong_truthfulness_winner_survives_three_family_direct_quota(self):
        paths = {
            TARGET_UID: "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_SPECIFIC_FACTS",
            "RUID-6aacf3fd76ca293f": (
                "TRUTHFULNESS.FABRICATED_EFFECT.FABRICATED_EFFECT_GENERAL"
            ),
            "RUID-fd8cb4eea586643c": (
                "CLAIM_EXPRESSION.GUARANTEE_COMMITMENT."
                "EFFECT_GUARANTEE_COMMITMENT"
            ),
            "RUID-4c6c470923121bc1": (
                "EVIDENCE_FACT.DATA_CITATION."
                "CITATION_LACKS_EVIDENCE_OR_SCIENTIFIC_BASIS"
            ),
        }
        expansion = {
            "direct_rule_uids": list(paths),
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
                for uid, issue_id in paths.items()
            ],
        }
        result = select_issue_tree_rules(
            expansion,
            [{"level_3_issue_id": issue_id} for issue_id in paths.values()],
            {uid: self.rules[uid] for uid in paths},
            {
                "context": {
                    "industry": "美妆",
                    "platforms": ["小红书"],
                    "product_category": "护肤",
                    "material_type": "图文",
                }
            },
            {
                "material_text": "7天美白3个度，99%用户见效，一次祛斑永不反弹。"
            },
            self.groups,
            semantic_scorer=lambda *args, **kwargs: {
                uid: {"semantic_score": 0.50} for uid in paths
            },
            per_path_limit=3,
            direct_limit=3,
        )
        self.assertIn(TARGET_UID, result["selected_direct_rule_uids"])
        allocation = next(
            item
            for item in result["quota_allocations"]
            if item["winning_rule_uid"] == TARGET_UID
        )
        self.assertEqual("family_coverage", allocation["allocation_phase"])


if __name__ == "__main__":
    unittest.main()
