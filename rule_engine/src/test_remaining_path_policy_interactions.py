# -*- coding: utf-8 -*-
"""Interaction tests for generic path preservation under path limits."""

import unittest

from issue_tree_targeted_path_policy import targeted_issue_paths


PATHS = (
    "SCOPE_ACCESS.AD_REVIEW_ACCESS.PRE_REVIEW_APPROVAL_AND_CONTENT_CONSISTENCY",
    "EVIDENCE_FACT.QUALIFICATION_FILING.PRODUCT_QUALIFICATION_MATERIAL_INCOMPLETE_OR_INCONSISTENT",
    "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_SPECIFIC_FACTS",
    "TRUTHFULNESS.MISLEADING_OMISSION.FALSE_ADVERTISING_GENERAL",
    "EVIDENCE_FACT.DATA_CITATION.CITATION_LACKS_SOURCE_SCOPE_OR_VALIDITY",
    "ENDORSEMENT.PROHIBITED_SUBJECT",
    "ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY",
    "ENDORSEMENT.ACTUAL_USE_DUTY.ENDORSER_RECOMMENDS_WITHOUT_ACTUAL_USE",
)


def _tree():
    branches = []
    for issue_id in PATHS:
        branches.append({
            "issue_id": issue_id.split(".", 1)[0],
            "children": [{
                "issue_id": issue_id.rsplit(".", 1)[0],
                "children": [{"issue_id": issue_id, "children": []}],
            }],
        })
    return {"branches": branches}


def _selected(context):
    return {
        item["level_3_issue_id"]
        for item in targeted_issue_paths(context, _tree())
    }


class RemainingPathPolicyInteractionTests(unittest.TestCase):
    def test_expert_endorsement_does_not_become_product_qualification_claim(self):
        selected = _selected({
            "material_text": "中国营养学会专家联名推荐，权威机构认证。",
            "supplemental_background": "未提供专家授权书、身份材料及实际使用证明。",
            "industry": "保健食品",
            "product_category": "营养补充剂",
        })
        self.assertIn("ENDORSEMENT.PROHIBITED_SUBJECT", selected)
        self.assertIn("ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY", selected)
        self.assertNotIn(
            "EVIDENCE_FACT.QUALIFICATION_FILING."
            "PRODUCT_QUALIFICATION_MATERIAL_INCOMPLETE_OR_INCONSISTENT",
            selected,
        )
        self.assertNotIn(
            "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_SPECIFIC_FACTS",
            selected,
        )

    def test_unsubstantiated_effect_statistics_preserve_truthfulness_path(self):
        selected = _selected({
            "material_text": "7天美白3个度，99%用户有效，效果永不反弹。",
            "supplemental_background": "未提供数据来源、样本量、统计口径及评价报告。",
            "industry": "美妆",
            "product_category": "护肤",
        })
        self.assertIn(
            "TRUTHFULNESS.MISLEADING_OMISSION.FALSE_ADVERTISING_GENERAL",
            selected,
        )

    def test_celebrity_claim_without_use_proof_preserves_actual_use_leaf(self):
        selected = _selected({
            "material_text": "某明星表示每天登录游戏并强烈推荐。",
            "supplemental_background": "没有代言人实际登录和使用记录证明。",
            "industry": "游戏",
            "product_category": "MOBA手游",
        })
        self.assertIn(
            "ENDORSEMENT.ACTUAL_USE_DUTY."
            "ENDORSER_RECOMMENDS_WITHOUT_ACTUAL_USE",
            selected,
        )


if __name__ == "__main__":
    unittest.main()
