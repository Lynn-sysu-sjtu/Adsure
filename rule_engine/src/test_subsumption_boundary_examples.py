# -*- coding: utf-8 -*-
import json
import unittest

from llm_judgment import build_judgment_messages


class SubsumptionBoundaryExampleTests(unittest.TestCase):
    def test_prompt_contains_product_attribute_counterexample(self):
        messages = build_judgment_messages(
            {"material_text": "这是我们的美白精华", "context_summary": "美妆广告"},
            [],
            mode="strict",
        )
        payload = json.loads(messages[-1]["content"])
        examples = payload["judgment_policy"]["boundary_examples"]
        example = next(item for item in examples if item["material"] == "这是我们的美白精华")

        self.assertEqual("needs_fact_verification", example["cosmetic_filing_rule"])
        self.assertEqual("not_applicable", example["fabricated_effect_rule"])
        self.assertIn("没有声称消费者已经取得实际美白效果", example["reason"])


if __name__ == "__main__":
    unittest.main()
