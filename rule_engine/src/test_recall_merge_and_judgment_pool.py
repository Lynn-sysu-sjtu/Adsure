import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rule_engine import (
    _matched_rule,
    _merge_recalled_rules,
    _select_judgment_recalled,
    audit,
)


class RecallMergeAndJudgmentPoolTests(unittest.TestCase):
    def test_merge_recalled_rules_collapses_parent_and_merges_unique_hits(self):
        first = {"rule_id": "RULE-001", "serial_no": 1, "risk_level": "中"}
        duplicate = {"rule_id": "RULE-001", "serial_no": 1, "risk_level": "中"}

        merged = _merge_recalled_rules(
            [
                (first, ["承诺", "承诺"]),
                (duplicate, ["semantic_embedding:0.711:scenario=open_rule"]),
            ]
        )

        self.assertEqual(1, len(merged))
        self.assertEqual(
            ["承诺", "semantic_embedding:0.711:scenario=open_rule"],
            merged[0][1],
        )

    def test_judgment_pool_is_capped_and_prefers_multi_channel_parent(self):
        recalled = [
            (
                {"rule_id": "MULTI-001", "serial_no": 3, "risk_level": "中"},
                ["侮辱", "semantic_embedding:0.700:scenario=insult"],
            ),
            (
                {"rule_id": "KEYWORD-001", "serial_no": 1, "risk_level": "高"},
                ["承诺"],
            ),
            (
                {"rule_id": "SEMANTIC-001", "serial_no": 2, "risk_level": "高"},
                ["semantic_embedding:0.800:scenario=summary"],
            ),
        ]

        selected = _select_judgment_recalled(recalled, limit=2)

        self.assertEqual(2, len(selected))
        self.assertEqual("MULTI-001", selected[0][0]["rule_id"])

    def test_judgment_pool_prefers_explicit_keyword_over_semantic_only_rule(self):
        keyword_rule = {
            "rule_id": "KEYWORD-001",
            "serial_no": 2,
            "risk_level": "高",
            "recall": {"trigger_layer": "content"},
        }
        semantic_rule = {
            "rule_id": "SEMANTIC-001",
            "serial_no": 1,
            "risk_level": "高",
            "recall": {"trigger_layer": "content"},
        }

        selected = _select_judgment_recalled(
            [
                (semantic_rule, ["semantic_embedding:0.950:scenario=noisy"]),
                (keyword_rule, ["疾病治疗"]),
            ],
            limit=1,
        )

        self.assertEqual("KEYWORD-001", selected[0][0]["rule_id"])

    def test_catalog_only_parent_uses_llm_catalog_recall_channel(self):
        matched = _matched_rule(
            {
                "rule_id": "OPEN-001",
                "title": "开放性规则",
                "recall": {"trigger_layer": "content"},
            },
            ["llm_catalog:隐喻羞辱"],
        )

        self.assertEqual("llm_catalog", matched["recall_channel"])

    def test_audit_keeps_full_matched_rules_but_sends_limited_pool_to_llm(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            jsonbase = base / "jsonbase"
            jsonbase.mkdir()
            rules = []
            for index in range(1, 4):
                rules.append(
                    {
                        "rule_id": f"RULE-{index:03d}",
                        "rule_uid": f"RUID-{index:03d}",
                        "serial_no": index,
                        "title": f"规则{index}",
                        "dimension": "测试维度",
                        "risk_level": "中",
                        "applies_to": {"industries": ["通用"]},
                        "detection": {"keyword_signals": {"hit_terms": ["共同词"]}},
                        "recall": {"trigger_layer": "content"},
                    }
                )
            (jsonbase / "rules.json").write_text(
                json.dumps({"meta": {}, "legal_sources": [], "rules": rules}, ensure_ascii=False),
                encoding="utf-8",
            )

            captured = {}

            def fake_judge(context_package, matched_rules):
                captured["rule_ids"] = [rule["rule_id"] for rule in matched_rules]
                return {
                    "engine": "fake",
                    "opinion_type": "风险提示",
                    "overall_risk_level": "中",
                    "audit_opinion": "测试",
                    "rule_judgments": [],
                    "outside_rule_risks": [],
                }

            with patch.dict(os.environ, {"ADSURE_JUDGMENT_POOL_LIMIT": "1"}, clear=False):
                with patch("rule_engine._judge_with_config", side_effect=fake_judge):
                    response = audit(
                        {
                            "record_id": "pool-test",
                            "mode": "标准",
                            "fields": {
                                "①运营·行业领域": "通用",
                                "①运营·物料内容": "共同词",
                            },
                        },
                        base_dir=base,
                    )

        self.assertEqual(0, response["code"])
        self.assertEqual(3, len(response["data"]["matched_rules"]))
        self.assertEqual(1, len(captured["rule_ids"]))


if __name__ == "__main__":
    unittest.main()
