# -*- coding: utf-8 -*-

import unittest

from deepseek_pre_review_workbench_v02 import (
    AI_FIELDS,
    build_prompt,
    validate_review,
)


class DeepSeekPreReviewWorkbenchTests(unittest.TestCase):
    def sample(self):
        return {
            "规则UID": "RUID-1",
            "规则标题": "保健食品广告不得使用代言人",
            "当前适用赛道": "保健食品",
            "当前全部问题ID": "ENDORSEMENT.HEALTH_FOOD",
            "当前映射角色": "legal_issue",
            "法规或平台规则": "中华人民共和国广告法",
            "条款": "第十八条",
            "规则原文": "保健食品广告不得利用广告代言人作推荐、证明。",
            "风险标签": "问题错配、中低置信度",
        }

    def valid_review(self):
        return {
            "rule_uid": "RUID-1",
            "suggested_track": "保健食品",
            "keep_issue_ids": ["ENDORSEMENT.HEALTH_FOOD"],
            "remove_issue_ids": [],
            "mapping_role": "direct",
            "audit_route": "普通文案召回",
            "asset_disposition": "保留",
            "submit_dispute": False,
            "confidence": "high",
            "reason": "原文直接禁止保健食品广告使用代言人。",
            "human_review_focus": "核对是否存在平台范围限制。",
        }

    def test_prompt_explains_legal_issue_is_transitional(self):
        prompt = build_prompt(self.sample(), [{"issue_id": "ENDORSEMENT.HEALTH_FOOD", "name": "保健食品禁止代言"}])
        self.assertIn("legal_issue", prompt)
        self.assertIn("过渡状态", prompt)
        self.assertIn("不能作为最终角色", prompt)

    def test_valid_review_passes_and_maps_all_ai_fields(self):
        result = validate_review(
            self.valid_review(),
            "RUID-1",
            {"ENDORSEMENT.HEALTH_FOOD"},
            {"ENDORSEMENT.HEALTH_FOOD"},
        )
        self.assertEqual(set(result), set(AI_FIELDS))
        self.assertEqual(result["AI建议最终映射角色"], "direct")
        self.assertEqual(result["AI建议最终审核链路"], "普通文案召回")

    def test_unknown_issue_requires_dispute_and_is_rejected(self):
        review = self.valid_review()
        review["keep_issue_ids"] = ["INVENTED.ISSUE"]
        with self.assertRaisesRegex(ValueError, "unknown issue"):
            validate_review(
                review,
                "RUID-1",
                {"ENDORSEMENT.HEALTH_FOOD"},
                {"ENDORSEMENT.HEALTH_FOOD"},
            )

    def test_legal_issue_cannot_be_final_role(self):
        review = self.valid_review()
        review["mapping_role"] = "legal_issue"
        with self.assertRaisesRegex(ValueError, "mapping_role"):
            validate_review(
                review,
                "RUID-1",
                {"ENDORSEMENT.HEALTH_FOOD"},
                {"ENDORSEMENT.HEALTH_FOOD"},
            )

    def test_empty_keep_issues_requires_dispute(self):
        review = self.valid_review()
        review["keep_issue_ids"] = []
        with self.assertRaisesRegex(ValueError, "submit_dispute"):
            validate_review(
                review,
                "RUID-1",
                {"ENDORSEMENT.HEALTH_FOOD"},
                {"ENDORSEMENT.HEALTH_FOOD"},
            )


if __name__ == "__main__":
    unittest.main()
