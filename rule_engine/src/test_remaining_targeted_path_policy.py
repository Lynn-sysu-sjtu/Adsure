# -*- coding: utf-8 -*-
"""Regression tests for generic high-confidence path preservation."""

import unittest

from issue_tree_targeted_path_policy import targeted_issue_paths


PATHS = (
    "TRUTHFULNESS.MISLEADING_OMISSION.FALSE_ADVERTISING_GENERAL",
    "EVIDENCE_FACT.DATA_CITATION.CITATION_LACKS_SOURCE_SCOPE_OR_VALIDITY",
    "ENDORSEMENT.PROHIBITED_SUBJECT",
    "ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY",
    "ENDORSEMENT.ACTUAL_USE_DUTY.ENDORSER_RECOMMENDS_WITHOUT_ACTUAL_USE",
    "MINORS_PUBLIC_ORDER.MINOR_PAYMENT.MINOR_ANTI_ADDICTION_CIRCUMVENTION",
    "SCOPE_ACCESS.SUBJECT_QUALIFICATION.ADVERTISER_QUALIFICATION_FALSE_OR_INVALID",
)


def _tree():
    branches = []
    for issue_id in PATHS:
        level_1 = issue_id.split(".", 1)[0]
        level_2 = issue_id.rsplit(".", 1)[0]
        branches.append({
            "issue_id": level_1,
            "children": [{
                "issue_id": level_2,
                "children": [{"issue_id": issue_id, "children": []}],
            }],
        })
    return {"branches": branches}


def _selected(context):
    return {
        item["level_3_issue_id"]: item
        for item in targeted_issue_paths(context, _tree())
    }


class RemainingTargetedPathPolicyTests(unittest.TestCase):
    def test_recommender_claim_without_proof_preserves_endorsement_paths(self):
        selected = _selected({
            "material_text": "中国营养学会专家联名推荐，权威心血管专家背书。",
            "supplemental_background": "未提供专家授权书、身份材料及实际使用证明。",
            "industry": "保健食品",
            "product_category": "营养补充剂",
        })
        self.assertIn("ENDORSEMENT.PROHIBITED_SUBJECT", selected)
        self.assertIn(
            "ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY",
            selected,
        )

    def test_data_claim_without_source_preserves_citation_fact_path(self):
        selected = _selected({
            "material_text": "7天美白3个度，99%用户有效。",
            "supplemental_background": "未提供数据来源、样本量、统计口径及适用范围。",
            "industry": "美妆",
            "product_category": "护肤",
        })
        issue_id = (
            "EVIDENCE_FACT.DATA_CITATION."
            "CITATION_LACKS_SOURCE_SCOPE_OR_VALIDITY"
        )
        self.assertIn(issue_id, selected)
        self.assertEqual("fact_check", selected[issue_id]["suggested_outcome"])

    def test_probability_hype_preserves_general_truthfulness_path(self):
        selected = _selected({
            "material_text": "限定角色高概率获取，错过只剩最后一次机会。",
            "supplemental_background": "实际基础概率为1.6%，累计90抽保底。",
            "industry": "游戏",
            "product_category": "二次元RPG手游",
        })
        self.assertIn(
            "TRUTHFULNESS.MISLEADING_OMISSION.FALSE_ADVERTISING_GENERAL",
            selected,
        )

    def test_no_real_name_and_no_license_preserve_access_paths(self):
        selected = _selected({
            "material_text": "无版号也能推广，注册不需要实名认证。",
            "supplemental_background": "客户确认游戏未取得版号。",
            "industry": "游戏",
            "product_category": "RPG手游",
        })
        self.assertIn(
            "MINORS_PUBLIC_ORDER.MINOR_PAYMENT."
            "MINOR_ANTI_ADDICTION_CIRCUMVENTION",
            selected,
        )
        self.assertIn(
            "SCOPE_ACCESS.SUBJECT_QUALIFICATION."
            "ADVERTISER_QUALIFICATION_FALSE_OR_INVALID",
            selected,
        )


if __name__ == "__main__":
    unittest.main()
