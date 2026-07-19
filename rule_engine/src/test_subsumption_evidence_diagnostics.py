# -*- coding: utf-8 -*-
import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class SubsumptionEvidenceDiagnosticTests(unittest.TestCase):
    def test_invalid_evidence_is_captured_only_in_internal_diagnostics(self):
        candidate = {
            "rule_uid": "RUID-ONE",
            "rule_id": "RULE-001",
            "title": "候选规则",
            "risk_level": "高",
            "dimension": "测试",
            "recall": {"trigger_layer": "content"},
        }
        judgment = {
            "rule_uid": "RUID-ONE",
            "rule_id": "RULE-001",
            "applicability_status": "confirmed_violation",
            "material_evidence": "测试文案（已确认）",
            "satisfied_elements": ["构成要件"],
            "unsatisfied_elements": [],
            "missing_facts": [],
            "applicability_reason": "测试",
            "confidence": 1.0,
        }
        diagnostics = {}
        with (
            patch("rule_engine.recall_rules", return_value=[(candidate, ["keyword"])]),
            patch("rule_engine.fact_recall_rules", return_value=[]),
            patch("rule_engine.load_legal_issue_groups", return_value={"groups": []}),
            patch(
                "rule_engine._judge_with_config",
                return_value={"overall_risk_level": "高", "rule_judgments": [judgment]},
            ),
        ):
            response = audit(
                {"record_id": "evidence-diagnostic", "industry": "通用", "content": "测试文案"},
                base_dir=PROJECT_BASE,
                diagnostics=diagnostics,
            )

        self.assertEqual(
            [{"rule_uid": "RUID-ONE", "rule_id": "RULE-001", "material_evidence": "测试文案（已确认）"}],
            diagnostics["judgment_evidence"],
        )
        self.assertNotIn("judgment_evidence", response["data"])


if __name__ == "__main__":
    unittest.main()
