import unittest

from legal_attention_calibration import build_calibration_rows, recommend_route_for_rule


class LegalAttentionCalibrationTests(unittest.TestCase):
    def test_recommends_operator_direct_for_clear_directly_fixable_rule(self):
        rule = {
            "rule_id": "CLEAR-001",
            "title": "clear wording issue",
            "recall": {"trigger_layer": "content"},
            "legal_attention": {
                "default_route": "legal_review_required",
                "trigger_clarity": "clear",
                "legal_interpretation_level": "low",
                "fact_verification_level": "none",
                "operator_fixability": "direct_fixable",
                "risk_severity": "medium",
            },
        }

        recommendation = recommend_route_for_rule(rule)

        self.assertEqual("operator_direct", recommendation["recommended_route"])
        self.assertEqual("high", recommendation["review_priority"])
        self.assertTrue(any("过度流转法务" in reason for reason in recommendation["reasons"]))

    def test_recommends_supply_docs_for_heavy_fact_rule_routed_directly(self):
        rule = {
            "rule_id": "FACT-001",
            "title": "requires proof",
            "recall": {"trigger_layer": "fact"},
            "legal_attention": {
                "default_route": "operator_direct",
                "trigger_clarity": "contextual",
                "legal_interpretation_level": "medium",
                "fact_verification_level": "heavy",
                "operator_fixability": "guided_fixable",
                "risk_severity": "medium",
            },
        }

        recommendation = recommend_route_for_rule(rule)

        self.assertEqual("operator_supply_docs", recommendation["recommended_route"])
        self.assertTrue(any("事实核验" in reason for reason in recommendation["reasons"]))

    def test_build_rows_merges_baseline_routing_failure_signal(self):
        rules = [
            {
                "rule_id": "ROUTE-001",
                "title": "overrouted rule",
                "_source_file": "rules.json",
                "recall": {"trigger_layer": "content"},
                "routing": {"default_route": "operator_direct"},
                "legal_attention": {
                    "default_route": "legal_review_required",
                    "trigger_clarity": "clear",
                    "legal_interpretation_level": "low",
                    "fact_verification_level": "none",
                    "operator_fixability": "direct_fixable",
                },
            }
        ]
        baseline_report = {
            "cases": [
                {
                    "case_id": "CASE-001",
                    "expected": {"expected_routing": "运营"},
                    "actual": {"routing": "法务", "matched_rule_ids": ["ROUTE-001"]},
                    "checks": {"routing_ok": False},
                }
            ]
        }

        rows = build_calibration_rows(rules, baseline_report=baseline_report)

        self.assertEqual(1, len(rows))
        self.assertEqual("ROUTE-001", rows[0]["rule_id"])
        self.assertEqual(1, rows[0]["baseline_failure_count"])
        self.assertEqual("expected_operator_actual_legal", rows[0]["baseline_failure_direction"])


if __name__ == "__main__":
    unittest.main()