# -*- coding: utf-8 -*-
"""Tests for the structured DeepSeek subsumption contract."""

import json
import unittest

from llm_judgment import build_judgment_messages, judge_with_mock_llm
from subsumption import validate_subsumption_result


class SubsumptionContractTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {
                "rule_uid": "RUID-CONTENT",
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "title": "广告不得违背社会良好风尚",
                "risk_level": "高",
                "recall_channel": "semantic",
                "match_reason": "像狗一样跑过来",
                "recall": {"trigger_layer": "content"},
            },
            {
                "rule_uid": "RUID-FACT",
                "rule_id": "COSM-002",
                "title": "普通化妆品不得宣称特殊功效",
                "risk_level": "高",
                "recall_channel": "fact",
                "match_reason": "美白精华",
                "recall": {"trigger_layer": "fact"},
            },
        ]
        self.context = {
            "material_text": "我们的美白精华一降价，你还不是像狗一样跑过来。",
            "industry": "美妆",
        }

    def test_prompt_requires_one_uid_judgment_per_candidate(self):
        messages = build_judgment_messages(self.context, self.rules, mode="strict")
        payload = json.loads(messages[-1]["content"])

        self.assertTrue(payload["judgment_policy"]["require_every_candidate_once"])
        self.assertEqual("rule_uid", payload["judgment_policy"]["identity_field"])
        self.assertEqual(
            "confirmed_violation | needs_fact_verification | not_applicable",
            payload["output_contract"]["rule_judgments"][0]["applicability_status"],
        )
        self.assertEqual(
            ["RUID-CONTENT", "RUID-FACT"],
            [item["rule_uid"] for item in payload["candidate_rules"]],
        )

    def test_prompt_distinguishes_keyword_relevance_from_rule_applicability(self):
        messages = build_judgment_messages(self.context, self.rules)
        payload = json.loads(messages[-1]["content"])

        policy_text = json.dumps(payload["judgment_policy"], ensure_ascii=False)
        self.assertIn("关键词", policy_text)
        self.assertIn("缺失事实", policy_text)
        self.assertIn("直接内容违规", policy_text)

    def test_mock_returns_one_structured_judgment_per_uid(self):
        result = judge_with_mock_llm(self.context, self.rules)

        self.assertEqual(2, len(result["rule_judgments"]))
        self.assertEqual(
            ["RUID-CONTENT", "RUID-FACT"],
            [item["rule_uid"] for item in result["rule_judgments"]],
        )
        self.assertEqual("confirmed_violation", result["rule_judgments"][0]["applicability_status"])
        self.assertEqual("needs_fact_verification", result["rule_judgments"][1]["applicability_status"])
        self.assertTrue(result["rule_judgments"][1]["missing_facts"])

    def test_final_rule_uses_title_and_legal_basis_from_selected_uid(self):
        candidates = [
            {
                "rule_uid": "RUID-FIRST",
                "rule_id": "DUPLICATE-001",
                "title": "first title",
                "legal_basis": [{"article": "first article"}],
            },
            {
                "rule_uid": "RUID-SECOND",
                "rule_id": "DUPLICATE-001",
                "title": "second title",
                "legal_basis": [{"article": "second article"}],
            },
        ]
        judgments = [
            {
                "rule_uid": "RUID-FIRST",
                "applicability_status": "confirmed_violation",
                "material_evidence": "evidence",
                "satisfied_elements": ["matched"],
                "unsatisfied_elements": [],
                "missing_facts": [],
                "applicability_reason": "first applies",
                "confidence": 1.0,
            },
            {
                "rule_uid": "RUID-SECOND",
                "applicability_status": "not_applicable",
                "material_evidence": "",
                "satisfied_elements": [],
                "unsatisfied_elements": ["not matched"],
                "missing_facts": [],
                "applicability_reason": "second does not apply",
                "confidence": 1.0,
            },
        ]

        result = validate_subsumption_result(candidates, judgments, "evidence")

        self.assertEqual(1, len(result.final_rules))
        self.assertEqual("RUID-FIRST", result.final_rules[0]["rule_uid"])
        self.assertEqual("first title", result.final_rules[0]["title"])
        self.assertEqual("first article", result.final_rules[0]["legal_basis"][0]["article"])


if __name__ == "__main__":
    unittest.main()
