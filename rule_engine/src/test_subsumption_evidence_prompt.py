# -*- coding: utf-8 -*-
import json
import unittest

from llm_judgment import build_judgment_messages


class SubsumptionEvidencePromptTests(unittest.TestCase):
    def test_prompt_forbids_joining_non_contiguous_evidence(self):
        messages = build_judgment_messages(
            {"material_text": "15天见效，全网第一，焕发新生", "context_summary": "美妆广告"},
            [{"rule_uid": "RUID-ONE", "rule_id": "RULE-001", "title": "测试规则"}],
            mode="strict",
        )
        payload = json.loads(messages[-1]["content"])
        policy = payload["judgment_policy"]["evidence_policy"]

        self.assertIn("单个连续片段", policy)
        self.assertIn("不得删除中间文字后拼接", policy)
        self.assertIn("只能选择其中一个连续片段", policy)


if __name__ == "__main__":
    unittest.main()
