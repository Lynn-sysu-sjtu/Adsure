# -*- coding: utf-8 -*-
import unittest

from run_engine_baseline_eval import evaluate_response, summarize_case_reports


class EngineBaselineSubsumptionMetricTests(unittest.TestCase):
    def test_evaluator_separates_candidates_confirmed_and_fact_verification(self):
        case = {
            "case_id": "CASE-SUB-001",
            "expected": {
                "must_recall_rule_ids": ["GEN-GOOD-CUSTOMS-001", "COSM-FALSE-004"],
                "expected_confirmed_rule_ids": ["GEN-GOOD-CUSTOMS-001"],
                "expected_fact_verification_rule_ids": ["COSM-002"],
                "expected_not_applicable_rule_ids": ["COSM-FALSE-004"],
                "expected_dimensions": ["社会良好风尚", "功效超备案"],
                "expected_risk_level": "高",
                "expected_routing": "法务",
            },
        }
        response = {
            "code": 0,
            "data": {
                "matched_rules": [
                    {
                        "rule_id": "GEN-GOOD-CUSTOMS-001",
                        "dimension": "社会良好风尚",
                        "applicability_status": "confirmed_violation",
                    },
                    {
                        "rule_id": "COSM-002",
                        "dimension": "功效超备案",
                        "applicability_status": "needs_fact_verification",
                    },
                ],
                "审核_推荐违规类型": ["社会良好风尚", "功效超备案"],
                "审核_推荐风险等级": "高",
                "routing": "法务",
                "risk_assessment": {
                    "rule_engine_risk_level": "高",
                    "llm_risk_level": "高",
                    "final_risk_level": "高",
                },
                "llm_judgment": {"engine": "deepseek_llm_v0", "rule_judgments": []},
            },
        }
        diagnostics = {
            "candidate_rule_ids": [
                "GEN-GOOD-CUSTOMS-001",
                "COSM-FALSE-004",
                "COSM-002",
            ]
        }

        report = evaluate_response(case, response, elapsed_ms=10, diagnostics=diagnostics)

        self.assertEqual(
            ["COSM-002", "COSM-FALSE-004", "GEN-GOOD-CUSTOMS-001"],
            report["actual"]["candidate_rule_ids"],
        )
        self.assertEqual(["GEN-GOOD-CUSTOMS-001"], report["actual"]["confirmed_rule_ids"])
        self.assertEqual(["COSM-002"], report["actual"]["fact_verification_rule_ids"])
        self.assertTrue(report["checks"]["candidate_recall_ok"])
        self.assertTrue(report["checks"]["confirmed_recall_ok"])
        self.assertTrue(report["checks"]["fact_verification_ok"])
        self.assertTrue(report["checks"]["not_applicable_filter_ok"])

    def test_summary_reports_compression_and_filter_metrics(self):
        reports = [
            {
                "checks": {
                    "response_ok": True,
                    "core_audit_ok": True,
                    "recall_ok": True,
                    "candidate_recall_ok": True,
                    "confirmed_recall_ok": True,
                    "fact_verification_ok": True,
                    "not_applicable_filter_ok": True,
                    "semantic_expected_ok": True,
                    "dimension_ok": True,
                    "risk_ok": True,
                    "rule_engine_risk_ok": True,
                    "llm_risk_ok": True,
                    "final_risk_ok": True,
                    "routing_ok": True,
                },
                "actual": {"candidate_rule_count": 4, "matched_rule_count": 2, "judgment_pool_count": 4},
                "risk_assessment": {},
                "llm_checks": {"json_valid": True, "rule_citation_ok": True},
                "semantic": {},
                "catalog": {},
                "elapsed_ms": 10,
                "error": None,
            }
        ]

        summary = summarize_case_reports(reports)

        self.assertEqual(1.0, summary["candidate_recall_rate"])
        self.assertEqual(1.0, summary["confirmed_recall_rate"])
        self.assertEqual(1.0, summary["fact_verification_accuracy"])
        self.assertEqual(1.0, summary["not_applicable_filter_accuracy"])
        self.assertEqual(4.0, summary["average_candidate_rule_count"])
        self.assertEqual(2.0, summary["average_final_rule_count"])
        self.assertEqual(0.5, summary["average_compression_ratio"])


if __name__ == "__main__":
    unittest.main()
