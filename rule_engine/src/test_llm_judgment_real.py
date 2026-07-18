import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_judgment import build_judgment_messages, judge_with_llm
from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class FakeChatClient:
    def __init__(self, payload):
        self.payload = payload
        self.messages = None
        self.model = None

    def create_chat_completion(self, messages, model=None, temperature=0.1, response_format=None):
        self.messages = messages
        self.model = model
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


class LlmJudgmentRealTests(unittest.TestCase):
    def test_strict_prompt_uses_candidate_rules_without_recall_internals(self):
        messages = build_judgment_messages(
            context_package={"material_text": "15\u5929\u89c1\u6548\uff0c\u5168\u7f51\u7b2c\u4e00", "context_summary": "\u7f8e\u5986\u62a4\u80a4\u6587\u6848"},
            matched_rules=[
                {
                    "rule_id": "GEN-ABS-001",
                    "title": "\u4e0d\u5f97\u4f7f\u7528\u7edd\u5bf9\u5316\u7528\u8bed",
                    "dimension": "\u7edd\u5bf9\u5316\u7528\u8bed",
                    "risk_level": "\u9ad8",
                    "legal_basis": ["AL\u7b2c\u56db\u6761"],
                    "vector_text": "\u4e0d\u8981\u6cc4\u6f0f\u53ec\u56de\u5185\u90e8\u5b57\u6bb5",
                    "tags": ["\u4e0d\u8981\u6cc4\u6f0f\u6807\u7b7e"],
                }
            ],
            mode="strict",
        )

        joined = "\n".join(message["content"] for message in messages)
        self.assertIn("\u53ea\u80fd\u57fa\u4e8e\u5019\u9009\u89c4\u5219", joined)
        self.assertIn("GEN-ABS-001", joined)
        self.assertIn("AL\u7b2c\u56db\u6761", joined)
        self.assertNotIn("vector_text", joined)
        self.assertNotIn("\u4e0d\u8981\u6cc4\u6f0f\u53ec\u56de\u5185\u90e8\u5b57\u6bb5", joined)
        self.assertNotIn("tags", joined)

    def test_expanded_prompt_allows_outside_rule_risks_with_label(self):
        messages = build_judgment_messages(
            context_package={"material_text": "\u7591\u4f3c\u5e73\u53f0\u89c4\u5219\u5916\u98ce\u9669", "context_summary": "\u6e38\u620f\u6587\u6848"},
            matched_rules=[],
            mode="expanded",
        )

        joined = "\n".join(message["content"] for message in messages)
        self.assertIn("\u89c4\u5219\u5e93\u5916\u98ce\u9669", joined)
        self.assertIn("\u4e0d\u5f97\u4f2a\u9020\u5177\u4f53\u6761\u6587", joined)

    def test_judge_with_llm_parses_json_response(self):
        client = FakeChatClient(
            {
                "overall_risk_level": "\u9ad8",
                "matched_rules": [
                    {
                        "rule_id": "GEN-ABS-001",
                        "is_violation": True,
                        "risk_level": "\u9ad8",
                        "reason": "\u4f7f\u7528\u5168\u7f51\u7b2c\u4e00",
                        "evidence": "\u5168\u7f51\u7b2c\u4e00",
                        "legal_basis": "AL\u7b2c\u56db\u6761",
                    }
                ],
                "outside_rule_risks": [],
                "audit_opinion": "\u5b58\u5728\u7edd\u5bf9\u5316\u7528\u8bed\u98ce\u9669\u3002",
                "revision_suggestion": "\u5220\u9664\u5168\u7f51\u7b2c\u4e00\u3002",
                "need_legal_review": True,
                "routing": "\u6cd5\u52a1",
            }
        )

        result = judge_with_llm(
            context_package={"material_text": "\u5168\u7f51\u7b2c\u4e00", "context_summary": "\u7f8e\u5986\u6587\u6848"},
            matched_rules=[{"rule_id": "GEN-ABS-001", "title": "\u4e0d\u5f97\u4f7f\u7528\u7edd\u5bf9\u5316\u7528\u8bed", "risk_level": "\u9ad8"}],
            mode="strict",
            client=client,
        )

        self.assertEqual("deepseek_llm_v0", result["engine"])
        self.assertEqual("strict", result["mode"])
        self.assertEqual("\u9ad8", result["overall_risk_level"])
        self.assertEqual("GEN-ABS-001", result["rule_judgments"][0]["rule_id"])
        self.assertEqual("\u6cd5\u52a1", result["routing"])

    def test_rule_engine_can_switch_to_real_llm_backend(self):
        os.environ["ADSURE_LLM_BACKEND"] = "deepseek"
        os.environ["ADSURE_LLM_MODE"] = "expanded"
        try:
            with patch("rule_engine.judge_with_llm") as fake_judge:
                fake_judge.return_value = {
                    "engine": "deepseek_llm_v0",
                    "mode": "expanded",
                    "overall_risk_level": "\u9ad8",
                    "audit_opinion": "\u771f\u5b9e LLM \u5224\u65ad\u5360\u4f4d\u3002",
                    "rule_judgments": [],
                    "summary": "",
                    "outside_rule_risks": [],
                    "revision_suggestion": "\u5220\u9664\u7edd\u5bf9\u5316\u8868\u8ff0\u3002",
                    "need_legal_review": True,
                    "routing": "\u6cd5\u52a1",
                }
                response = audit(
                    {
                        "record_id": "rec_real_llm_switch",
                        "mode": "\u6807\u51c6",
                        "fields": {
                            "\u2460\u8fd0\u8425\u00b7\u884c\u4e1a\u9886\u57df": "\u7f8e\u5986",
                            "\u2460\u8fd0\u8425\u00b7\u7269\u6599\u5185\u5bb9": "\u5168\u7f51\u7b2c\u4e00\uff0c15\u5929\u89c1\u6548",
                            "\u2460\u7f8e\u5986\u00b7\u7269\u6599\u7c7b\u578b": "Banner",
                            "\u2460\u7f8e\u5986\u00b7\u6295\u653e\u5e73\u53f0": ["\u6296\u97f3"],
                            "\u2460\u7f8e\u5986\u00b7\u4ea7\u54c1\u54c1\u7c7b": "\u62a4\u80a4",
                            "\u2460\u7f8e\u5986\u00b7\u6838\u5fc3\u5ba3\u79f0\u529f\u6548": "\u6539\u5584\u80a4\u8272",
                        },
                    },
                    base_dir=PROJECT_BASE,
                )
        finally:
            os.environ.pop("ADSURE_LLM_BACKEND", None)
            os.environ.pop("ADSURE_LLM_MODE", None)

        self.assertEqual(0, response["code"])
        self.assertEqual("deepseek_llm_v0", response["data"]["llm_judgment"]["engine"])
        fake_judge.assert_called_once()


if __name__ == "__main__":
    unittest.main()
