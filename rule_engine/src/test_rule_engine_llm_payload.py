import unittest

from llm_judgment import build_judgment_messages
from rule_engine import _matched_rule


class RuleEngineLlmPayloadTests(unittest.TestCase):
    def test_matched_rule_carries_full_rule_context_for_llm(self):
        rule = {
            "rule_id": "GEN-FALSE-001",
            "serial_no": 1,
            "title": "广告不得作虚假或者引人误解的宣传",
            "dimension": "虚假宣传",
            "risk_level": "高",
            "applies_to": {"industries": ["通用", "美妆"]},
            "preconditions": {"required_context_fields": ["content"]},
            "rule_nature": "flexible",
            "routing": {"default_route": "legal_review_required"},
            "review_required": True,
            "legal_basis": [
                {
                    "source_id": "AL",
                    "article": "第二十八条",
                    "text": "广告以虚假或者引人误解的内容欺骗、误导消费者的，构成虚假广告。",
                }
            ],
            "detection": {
                "semantic_criteria": "判断广告是否对商品效果、价格、荣誉等作出与实际不符或无法证明的表示。",
                "decision": "如果宣传内容无法证明且足以影响购买决策，则判定为虚假宣传风险。",
            },
            "recall": {
                "vector_text": "不应该进入 LLM 判断池的召回内部字段",
                "tags": ["不应该进入 LLM 判断池"],
            },
        }

        matched = _matched_rule(rule, ["semantic_embedding:0.881"])

        self.assertEqual("GEN-FALSE-001", matched["rule_id"])
        self.assertEqual("semantic", matched["recall_channel"])
        self.assertEqual(rule["legal_basis"], matched["legal_basis_detail"])
        self.assertEqual(rule["applies_to"], matched["applies_to"])
        self.assertEqual(rule["preconditions"], matched["preconditions"])
        self.assertEqual("flexible", matched["rule_nature"])
        self.assertEqual(rule["routing"], matched["routing"])
        self.assertTrue(matched["review_required"])
        self.assertEqual(rule["detection"]["semantic_criteria"], matched["semantic_criteria"])
        self.assertEqual(rule["detection"]["decision"], matched["decision"])
        self.assertNotIn("vector_text", matched)
        self.assertNotIn("tags", matched)

    def test_llm_prompt_requires_opinion_type_enum(self):
        messages = build_judgment_messages(
            {"material_text": "充 3 元送一只狗", "context_summary": "游戏 Banner"},
            [],
            mode="strict",
        )
        prompt = "\n".join(message["content"] for message in messages)

        self.assertIn("opinion_type", prompt)
        self.assertIn("风险提示", prompt)
        self.assertIn("违规修改", prompt)
        self.assertIn("需补资料", prompt)
        self.assertIn("无明显风险", prompt)
    def test_llm_prompt_receives_full_matched_rule_context(self):
        rule = {
            "rule_id": "GEN-FALSE-001",
            "title": "????????????????",
            "dimension": "????",
            "risk_level": "?",
            "applies_to": {"industries": ["??", "??"]},
            "preconditions": {"logic": "??????????"},
            "rule_nature": "flexible",
            "routing": {"default_route": "legal_review_required"},
            "legal_basis": [{"source_id": "AL", "article": "?????", "text": "???????"}],
            "detection": {
                "semantic_criteria": "???????????????",
                "decision": "????????????????",
            },
        }
        matched = _matched_rule(rule, ["??"])

        messages = build_judgment_messages(
            {"material_text": "15???", "context_summary": "??????"},
            [matched],
            mode="strict",
        )
        prompt = "\n".join(message["content"] for message in messages)

        self.assertIn("applies_to", prompt)
        self.assertIn("preconditions", prompt)
        self.assertIn("rule_nature", prompt)
        self.assertIn("routing", prompt)
        self.assertIn("??????", prompt)
        self.assertIn("??????????????", prompt)
        self.assertNotIn("vector_text", prompt)


if __name__ == "__main__":
    unittest.main()

