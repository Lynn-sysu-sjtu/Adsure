# -*- coding: utf-8 -*-
"""Tests for conservative manual-review fallback when subsumption fails."""

import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class SubsumptionFailureFallbackTests(unittest.TestCase):
    def test_llm_exception_returns_contract_safe_manual_review(self):
        candidate = {
            "rule_uid": "RUID-ONE",
            "rule_id": "RULE-001",
            "title": "候选规则",
            "risk_level": "高",
            "dimension": "测试",
            "recall": {"trigger_layer": "content"},
        }
        with (
            patch("rule_engine.recall_rules", return_value=[(candidate, ["keyword"])]),
            patch("rule_engine.fact_recall_rules", return_value=[]),
            patch("rule_engine.load_legal_issue_groups", return_value={"groups": []}),
            patch("rule_engine._judge_with_config", side_effect=TimeoutError("provider timeout")),
        ):
            response = audit(
                {"record_id": "fallback", "industry": "美妆", "content": "测试文案"},
                base_dir=PROJECT_BASE,
            )

        data = response["data"]
        self.assertEqual(0, response["code"])
        self.assertEqual("中", data["预审_风险等级"])
        self.assertEqual("中", data["审核_推荐风险等级"])
        self.assertEqual("法务", data["routing"])
        self.assertEqual([], data["matched_rules"])
        self.assertIn("人工复核", data["审核_审核意见"])
        self.assertNotIn("provider timeout", data["审核_审核意见"])

    def test_invalid_incomplete_judgments_use_same_fallback(self):
        candidate = {
            "rule_uid": "RUID-ONE",
            "rule_id": "RULE-001",
            "title": "候选规则",
            "risk_level": "高",
            "dimension": "测试",
            "recall": {"trigger_layer": "content"},
        }
        with (
            patch("rule_engine.recall_rules", return_value=[(candidate, ["keyword"])]),
            patch("rule_engine.fact_recall_rules", return_value=[]),
            patch("rule_engine.load_legal_issue_groups", return_value={"groups": []}),
            patch(
                "rule_engine._judge_with_config",
                return_value={
                    "engine": "deepseek_llm_v0",
                    "overall_risk_level": "高",
                    "audit_opinion": "",
                    "rule_judgments": [],
                },
            ),
        ):
            response = audit(
                {"record_id": "fallback-invalid", "industry": "美妆", "content": "测试文案"},
                base_dir=PROJECT_BASE,
            )

        self.assertEqual([], response["data"]["matched_rules"])
        self.assertEqual("法务", response["data"]["routing"])


if __name__ == "__main__":
    unittest.main()
