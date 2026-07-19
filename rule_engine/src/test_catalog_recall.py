import json
import os
import unittest
from unittest.mock import patch

from catalog_recall import (
    build_catalog_messages,
    catalog_recall_rules,
    parse_catalog_response,
)


RULES = [
    {
        "rule_id": "OPEN-001",
        "title": "开放规则一",
        "dimension": "良好风尚",
        "recall": {
            "trigger_layer": "content",
            "catalog_recall_enabled": True,
            "catalog_text": "侮辱物化消费者",
            "catalog_group": "values",
        },
    },
    {
        "rule_id": "OPEN-002",
        "title": "开放规则二",
        "dimension": "公共利益",
        "recall": {
            "trigger_layer": "content",
            "catalog_recall_enabled": True,
            "catalog_text": "利用灾难制造恐慌",
            "catalog_group": "public_interest",
        },
    },
]


class CatalogRecallTests(unittest.TestCase):
    def test_catalog_recall_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            recalled = catalog_recall_rules(RULES, {}, {}, backend="mock")

        self.assertEqual([], recalled)

    def test_mock_response_filters_unknown_ids_deduplicates_and_limits(self):
        response = {
            "selected_rule_ids": ["OPEN-001", "UNKNOWN", "OPEN-001", "OPEN-002"],
            "reason": "存在开放性风险",
        }

        recalled = catalog_recall_rules(
            RULES,
            {},
            {},
            backend="mock",
            enabled=True,
            limit=1,
            mock_response=response,
        )

        self.assertEqual(["OPEN-001"], [rule["rule_id"] for rule, _ in recalled])
        self.assertEqual(["llm_catalog:存在开放性风险"], recalled[0][1])

    def test_parse_catalog_response_returns_empty_for_malformed_json(self):
        self.assertEqual([], parse_catalog_response("not-json", {"OPEN-001"}, limit=3))

    def test_catalog_prompt_contains_compact_directory_and_no_risk_task(self):
        messages = build_catalog_messages(
            {
                "content": "像狗一样跑过来",
                "industry": "通用",
                "existing_candidate_rules": [
                    {
                        "rule_id": "GEN-COMPARE-001",
                        "title": "不得贬低其他经营者",
                        "dimension": "竞品贬低",
                    }
                ],
            },
            [
                {
                    "rule_id": "OPEN-001",
                    "title": "开放规则一",
                    "dimension": "良好风尚",
                    "catalog_text": "侮辱物化消费者",
                    "catalog_group": "values",
                    "trigger_layer": "content",
                }
            ],
            limit=3,
        )

        payload = json.loads(messages[1]["content"])
        self.assertEqual(["OPEN-001"], [item["rule_id"] for item in payload["rule_directory"]])
        self.assertNotIn("risk_level", messages[1]["content"])
        self.assertIn("不得判断是否违法", messages[0]["content"])
        self.assertIn("默认返回空数组", messages[0]["content"])
        self.assertIn("原文证据", messages[0]["content"])
        self.assertIn("不得重复选择", messages[0]["content"])
        self.assertEqual(
            ["GEN-COMPARE-001"],
            [
                item["rule_id"]
                for item in payload["existing_candidate_rules"]
            ],
        )

    def test_deepseek_backend_uses_json_response_and_returns_allowed_rule(self):
        class FakeClient:
            def create_chat_completion(self, messages, **kwargs):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "selected_rules": [
                                            {
                                                "rule_id": "OPEN-002",
                                                "evidence": "利用灾难制造恐慌",
                                                "reason": "直接描述制造恐慌",
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }

        recalled = catalog_recall_rules(
            RULES,
            {},
            {"material_text": "利用灾难制造恐慌"},
            backend="deepseek",
            enabled=True,
            client=FakeClient(),
        )

        self.assertEqual(["OPEN-002"], [rule["rule_id"] for rule, _ in recalled])

    def test_deepseek_backend_rejects_invented_evidence(self):
        class FakeClient:
            def create_chat_completion(self, messages, **kwargs):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "selected_rules": [
                                            {
                                                "rule_id": "OPEN-001",
                                                "evidence": "文案中不存在的羞辱表达",
                                                "reason": "猜测可能相关",
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                }

        recalled = catalog_recall_rules(
            RULES,
            {},
            {"material_text": "普通促销文案"},
            backend="deepseek",
            enabled=True,
            client=FakeClient(),
        )

        self.assertEqual([], recalled)

    def test_deepseek_backend_exception_falls_back_to_empty(self):
        class BrokenClient:
            def create_chat_completion(self, messages, **kwargs):
                raise RuntimeError("provider unavailable")

        recalled = catalog_recall_rules(
            RULES,
            {},
            {"material_text": "测试"},
            backend="deepseek",
            enabled=True,
            client=BrokenClient(),
        )

        self.assertEqual([], recalled)



if __name__ == "__main__":
    unittest.main()
