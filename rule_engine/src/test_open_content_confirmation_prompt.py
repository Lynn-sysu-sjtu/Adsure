# -*- coding: utf-8 -*-
import json
import unittest

from llm_judgment import build_judgment_messages


class OpenContentConfirmationPromptTests(unittest.TestCase):
    def test_prompt_confirms_direct_dehumanizing_expression_without_fact_check(self):
        messages = build_judgment_messages(
            {
                "material_text": "我们一降价，你还不是像狗一样跑过来",
                "context_summary": "通用广告",
            },
            [],
            mode="strict",
        )
        payload = json.loads(messages[-1]["content"])
        examples = payload["judgment_policy"]["boundary_examples"]
        example = next(
            item
            for item in examples
            if item["material"] == "我们一降价，你还不是像狗一样跑过来"
        )

        self.assertEqual("confirmed_violation", example["good_customs_rule"])
        self.assertEqual([], example["missing_facts"])
        self.assertIn("可直接根据文案原文完成价值判断", example["reason"])
        self.assertIn("不得降级为needs_fact_verification", example["reason"])


if __name__ == "__main__":
    unittest.main()
