import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit
from run_engine_baseline_eval import evaluate_response, summarize_case_reports


PROJECT_BASE = Path(__file__).resolve().parents[1]


class RiskAssessmentDualTrackTests(unittest.TestCase):
    def test_rule_engine_outputs_dual_track_risk_assessment(self):
        with patch("rule_engine.judge_with_mock_llm") as fake_judge:
            fake_judge.return_value = {
                "engine": "mock_llm_v0",
                "overall_risk_level": "中",
                "audit_opinion": "LLM 认为个案风险为中。",
                "rule_judgments": [{"rule_id": "GEN-ABS-001"}],
                "summary": "",
            }
            response = audit(
                {
                    "record_id": "rec_dual_risk",
                    "mode": "标准",
                    "fields": {
                        "①运营·行业领域": "美妆",
                        "①运营·物料内容": "全网第一，15天见效",
                        "①美妆·物料类型": "Banner",
                        "①美妆·投放平台": ["抖音"],
                        "①美妆·产品品类": "护肤",
                        "①美妆·核心宣称功效": "改善肤色",
                    },
                },
                base_dir=PROJECT_BASE,
            )

        data = response["data"]
        assessment = data["risk_assessment"]
        self.assertEqual("高", assessment["rule_engine_risk_level"])
        self.assertEqual("中", assessment["llm_risk_level"])
        self.assertEqual("高", assessment["final_risk_level"])
        self.assertTrue(assessment["risk_disagreement"])
        self.assertEqual("rule_engine_default", assessment["final_risk_source"])
        self.assertEqual("高", data["审核_推荐风险等级"])

    def test_eval_reports_rule_llm_final_risk_metrics(self):
        case = {
            "case_id": "CASE-RISK-001",
            "expected": {
                "must_recall_rule_ids": ["GEN-ABS-001"],
                "expected_dimensions": ["绝对化用语"],
                "expected_risk_level": "高",
                "expected_routing": "法务",
            },
        }
        response = {
            "code": 0,
            "data": {
                "审核_推荐违规类型": ["绝对化用语"],
                "审核_推荐风险等级": "高",
                "matched_rules": [{"rule_id": "GEN-ABS-001", "recall_channel": "keyword"}],
                "routing": "法务",
                "risk_assessment": {
                    "rule_engine_risk_level": "高",
                    "llm_risk_level": "中",
                    "final_risk_level": "高",
                    "risk_disagreement": True,
                    "final_risk_source": "rule_engine_default",
                },
                "llm_judgment": {
                    "engine": "deepseek_llm_v0",
                    "overall_risk_level": "中",
                    "rule_judgments": [{"rule_id": "GEN-ABS-001"}],
                    "outside_rule_risks": [],
                },
            },
        }

        report = evaluate_response(case, response, elapsed_ms=5)
        summary = summarize_case_reports([report])

        self.assertTrue(report["checks"]["rule_engine_risk_ok"])
        self.assertFalse(report["checks"]["llm_risk_ok"])
        self.assertTrue(report["checks"]["final_risk_ok"])
        self.assertTrue(report["risk_assessment"]["risk_disagreement"])
        self.assertEqual(1.0, summary["rule_engine_risk_match_rate"])
        self.assertEqual(0.0, summary["llm_risk_match_rate"])
        self.assertEqual(1.0, summary["final_risk_match_rate"])
        self.assertEqual(1, summary["risk_disagreement_count"])


if __name__ == "__main__":
    unittest.main()
