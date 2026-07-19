# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class SubsumptionDiagnosticTests(unittest.TestCase):
    def test_validation_failure_is_internal_diagnostic_only(self):
        candidate = {
            "rule_uid": "RUID-ONE",
            "rule_id": "RULE-001",
            "title": "候选规则",
            "risk_level": "高",
            "dimension": "测试",
            "recall": {"trigger_layer": "content"},
        }
        diagnostics = {}
        with (
            patch("rule_engine.recall_rules", return_value=[(candidate, ["keyword"])]),
            patch("rule_engine.fact_recall_rules", return_value=[]),
            patch("rule_engine.load_legal_issue_groups", return_value={"groups": []}),
            patch(
                "rule_engine._judge_with_config",
                return_value={"overall_risk_level": "高", "rule_judgments": []},
            ),
        ):
            response = audit(
                {"record_id": "diagnostic", "industry": "通用", "content": "测试文案"},
                base_dir=PROJECT_BASE,
                diagnostics=diagnostics,
            )

        self.assertEqual("subsumption_validation_failed", diagnostics["fallback_reason_code"])
        self.assertIn("Every candidate must be judged exactly once", diagnostics["fallback_detail"])
        self.assertNotIn("fallback_detail", response["data"])
        self.assertNotIn("Every candidate", response["data"]["审核_审核意见"])


if __name__ == "__main__":
    unittest.main()
