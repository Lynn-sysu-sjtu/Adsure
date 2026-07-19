# -*- coding: utf-8 -*-
import json
import unittest

from llm_judgment import build_judgment_messages


class SubsumptionMissingFactBoundaryPromptTests(unittest.TestCase):
    def test_prompt_distinguishes_missing_proof_from_missing_rule_predicate(self):
        messages = build_judgment_messages(
            {"material_text": "这是我们的美白精华", "context_summary": "美妆广告"},
            [
                {"rule_uid": "RUID-COSM", "rule_id": "COSM-002", "title": "普通化妆品不得宣称特殊功效"},
                {"rule_uid": "RUID-FALSE", "rule_id": "COSM-FALSE-004", "title": "虚构使用效果构成虚假广告"},
            ],
            mode="strict",
        )
        payload = json.loads(messages[-1]["content"])
        policy = payload["judgment_policy"]["missing_fact_boundary"]

        self.assertIn("不能用缺少证明材料代替构成要件", policy)
        self.assertIn("产品名称或属性描述", policy)
        self.assertIn("虚构效果规则应为not_applicable", policy)
        self.assertIn("备案或资质规则可为needs_fact_verification", policy)


if __name__ == "__main__":
    unittest.main()
