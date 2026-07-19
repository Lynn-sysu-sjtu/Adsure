import os
import unittest
from unittest.mock import patch

from run_engine_baseline_eval import evaluate_response, filter_cases_by_layer, summarize_case_reports


class EngineBaselineEvalTests(unittest.TestCase):
    def test_filter_cases_by_layer_defaults_to_content_cases(self):
        cases = [
            {"case_id": "CONTENT-001"},
            {"case_id": "CONTENT-002", "case_layer": "content"},
            {"case_id": "WORKFLOW-001", "case_layer": "workflow"},
        ]

        self.assertEqual(
            ["CONTENT-001", "CONTENT-002"],
            [case["case_id"] for case in filter_cases_by_layer(cases)],
        )
        self.assertEqual(
            ["WORKFLOW-001"],
            [case["case_id"] for case in filter_cases_by_layer(cases, {"workflow"})],
        )

    def test_evaluate_response_separates_core_audit_from_routing(self):
        case = {
            "case_id": "CASE-001",
            "name": "routing mismatch should not fail core audit",
            "expected": {
                "must_recall_rule_ids": ["GEN-ABS-001"],
                "expected_dimensions": ["绝对化用语"],
                "expected_risk_level": "高",
                "expected_routing": "运营",
            },
        }
        response = {
            "code": 0,
            "msg": "ok",
            "data": {
                "审核_推荐违规类型": ["绝对化用语"],
                "审核_推荐风险等级": "高",
                "matched_rules": [
                    {
                        "rule_id": "GEN-ABS-001",
                        "recall_channel": "keyword",
                    }
                ],
                "llm_judgment": {
                    "engine": "mock_llm_v0",
                    "rule_judgments": [{"rule_id": "GEN-ABS-001"}],
                    "outside_rule_risks": [],
                },
                "routing": "法务",
            },
        }

        report = evaluate_response(case, response, elapsed_ms=12)

        self.assertTrue(report["checks"]["recall_ok"])
        self.assertTrue(report["checks"]["dimension_ok"])
        self.assertTrue(report["checks"]["risk_ok"])
        self.assertFalse(report["checks"]["routing_ok"])
        self.assertTrue(report["checks"]["core_audit_ok"])
        self.assertEqual(["GEN-ABS-001"], report["actual"]["matched_rule_ids"])
        self.assertEqual([], report["llm_checks"]["hallucinated_rule_ids"])

    def test_evaluate_response_includes_rule_details_for_failure_diagnosis(self):
        case = {
            "case_id": "CASE-ROUTE-001",
            "name": "routing diagnosis should show rule metadata",
            "expected": {
                "must_recall_rule_ids": ["GEN-ABS-001"],
                "expected_dimensions": ["绝对化用语"],
                "expected_risk_level": "中",
                "expected_routing": "运营",
            },
        }
        response = {
            "code": 0,
            "msg": "ok",
            "data": {
                "审核_推荐违规类型": ["绝对化用语"],
                "审核_推荐风险等级": "高",
                "matched_rules": [
                    {
                        "rule_id": "GEN-ABS-001",
                        "rule_uid": "RUID-test-001",
                        "title": "广告不得使用绝对化用语",
                        "risk_level": "高",
                        "recall_channel": "keyword",
                        "recall": {"trigger_layer": "content"},
                        "legal_attention": {
                            "default_route": "operator_direct",
                            "legal_interpretation_level": "low",
                            "fact_verification_level": "none",
                            "operator_fixability": "direct_fixable",
                        },
                    }
                ],
                "risk_assessment": {
                    "rule_engine_risk_level": "高",
                    "llm_risk_level": "中",
                    "final_risk_level": "高",
                    "final_risk_source": "llm_case_adjusted",
                    "final_risk_reason": "LLM 个案判断为中风险，最终风险按个案风险确定。",
                },
                "llm_judgment": {
                    "engine": "mock_llm_v0",
                    "rule_judgments": [{"rule_id": "GEN-ABS-001"}],
                    "outside_rule_risks": [],
                },
                "routing": "法务",
            },
        }

        report = evaluate_response(case, response, elapsed_ms=12)

        self.assertEqual("llm_case_adjusted", report["risk_assessment"]["final_risk_source"])
        self.assertIn("LLM 个案判断", report["risk_assessment"]["final_risk_reason"])
        self.assertEqual(
            [
                {
                    "rule_id": "GEN-ABS-001",
                    "rule_uid": "RUID-test-001",
                    "title": "广告不得使用绝对化用语",
                    "trigger_layer": "content",
                    "legal_attention_default_route": "operator_direct",
                    "risk_level": "高",
                    "recall_channel": "keyword",
                }
            ],
            report["actual"]["matched_rule_details"],
        )
    def test_summarize_case_reports_counts_llm_metrics(self):
        reports = [
            {
                "checks": {
                    "response_ok": True,
                    "core_audit_ok": True,
                    "recall_ok": True,
                    "dimension_ok": True,
                    "risk_ok": True,
                    "routing_ok": False,
                },
                "llm_checks": {
                    "json_valid": True,
                    "rule_citation_ok": True,
                    "hallucinated_rule_ids": [],
                    "outside_rule_risk_count": 1,
                },
                "semantic": {"semantic_matched_rule_ids": ["GEN-IDENT-001"]},
                "elapsed_ms": 10,
            },
            {
                "checks": {
                    "response_ok": True,
                    "core_audit_ok": False,
                    "recall_ok": False,
                    "dimension_ok": True,
                    "risk_ok": False,
                    "routing_ok": True,
                },
                "llm_checks": {
                    "json_valid": True,
                    "rule_citation_ok": False,
                    "hallucinated_rule_ids": ["FAKE-001"],
                    "outside_rule_risk_count": 2,
                },
                "semantic": {"semantic_matched_rule_ids": []},
                "elapsed_ms": 30,
            },
        ]

        summary = summarize_case_reports(reports)

        self.assertEqual(2, summary["case_count"])
        self.assertEqual(0.5, summary["core_audit_pass_rate"])
        self.assertEqual(0.5, summary["routing_pass_rate"])
        self.assertEqual(1, summary["semantic_matched_case_count"])
        self.assertEqual(1, summary["llm_hallucination_case_count"])
        self.assertEqual(3, summary["outside_rule_risk_count"])
        self.assertEqual(20.0, summary["average_elapsed_ms"])

    def test_report_tracks_catalog_matches_pool_size_and_latency_percentiles(self):
        case = {
            "case_id": "CASE-CATALOG-001",
            "expected": {
                "must_recall_rule_ids": ["OPEN-001"],
                "expected_dimensions": ["良好风尚"],
                "expected_risk_level": "高",
                "expected_routing": "法务",
            },
        }
        matched_rules = [
            {
                "rule_id": f"RULE-{index:03d}",
                "recall_channel": "keyword",
            }
            for index in range(9)
        ]
        matched_rules.append(
            {
                "rule_id": "OPEN-001",
                "recall_channel": "semantic",
                "raw_hit_terms": [
                    "llm_catalog:开放性风险",
                ],
            }
        )
        response = {
            "code": 0,
            "data": {
                "审核_推荐违规类型": ["良好风尚"],
                "审核_推荐风险等级": "高",
                "matched_rules": matched_rules,
                "routing": "法务",
                "llm_judgment": {
                    "engine": "mock",
                    "rule_judgments": [{"rule_id": "OPEN-001"}],
                    "outside_rule_risks": [],
                },
            },
        }

        with patch.dict(os.environ, {"ADSURE_JUDGMENT_POOL_LIMIT": "8"}, clear=False):
            report = evaluate_response(case, response, elapsed_ms=25)
            summary = summarize_case_reports([report])

        self.assertEqual(10, report["actual"]["matched_rule_count"])
        self.assertEqual(8, report["actual"]["judgment_pool_count"])
        self.assertEqual(["OPEN-001"], report["catalog"]["catalog_matched_rule_ids"])
        self.assertEqual(1, summary["catalog_matched_case_count"])
        self.assertEqual(10.0, summary["average_matched_rule_count"])
        self.assertEqual(8.0, summary["average_judgment_pool_count"])
        self.assertEqual(25, summary["p50_elapsed_ms"])
        self.assertEqual(25, summary["p95_elapsed_ms"])

    def test_summarize_handles_failed_case_without_semantic_payload(self):
        reports = [
            {
                "checks": {
                    "response_ok": False,
                    "core_audit_ok": False,
                    "recall_ok": False,
                    "dimension_ok": False,
                    "risk_ok": False,
                    "routing_ok": False,
                },
                "semantic": {},
                "llm_checks": {
                    "json_valid": False,
                    "rule_citation_ok": False,
                    "hallucinated_rule_ids": [],
                    "outside_rule_risk_count": 0,
                },
                "elapsed_ms": 1,
                "error": "embedding service failed",
            }
        ]

        summary = summarize_case_reports(reports)

        self.assertEqual(1, summary["case_count"])
        self.assertEqual(0, summary["semantic_matched_case_count"])
        self.assertEqual(0.0, summary["core_audit_pass_rate"])


if __name__ == "__main__":
    unittest.main()
