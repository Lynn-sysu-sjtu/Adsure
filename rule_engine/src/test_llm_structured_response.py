# -*- coding: utf-8 -*-
"""Tests for preserving structured DeepSeek rule judgments."""

import json
import unittest

from llm_judgment import judge_with_llm


class StructuredClient:
    def create_chat_completion(self, messages, **kwargs):
        payload = {
            "opinion_type": "违规修改",
            "overall_risk_level": "高",
            "rule_judgments": [
                {
                    "rule_uid": "RUID-GOOD",
                    "rule_id": "GEN-GOOD-CUSTOMS-001",
                    "applicability_status": "confirmed_violation",
                    "material_evidence": "像狗一样跑过来",
                    "satisfied_elements": ["动物化贬损"],
                    "unsatisfied_elements": [],
                    "missing_facts": [],
                    "applicability_reason": "直接贬损消费者人格",
                    "confidence": 0.96,
                }
            ],
            "outside_rule_risks": [],
            "audit_opinion": "意见类型：违规修改",
            "revision_suggestion": "删除侮辱性表达",
            "need_legal_review": True,
            "routing": "法务",
        }
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


class LlmStructuredResponseTests(unittest.TestCase):
    def test_preserves_structured_uid_judgment_fields(self):
        result = judge_with_llm(
            {"material_text": "像狗一样跑过来", "context_summary": "测试"},
            [
                {
                    "rule_uid": "RUID-GOOD",
                    "rule_id": "GEN-GOOD-CUSTOMS-001",
                    "title": "广告不得违背社会良好风尚",
                    "risk_level": "高",
                }
            ],
            client=StructuredClient(),
        )

        judgment = result["rule_judgments"][0]
        self.assertEqual("RUID-GOOD", judgment["rule_uid"])
        self.assertEqual("confirmed_violation", judgment["applicability_status"])
        self.assertEqual("像狗一样跑过来", judgment["material_evidence"])
        self.assertEqual(["动物化贬损"], judgment["satisfied_elements"])
        self.assertEqual(0.96, judgment["confidence"])


if __name__ == "__main__":
    unittest.main()
