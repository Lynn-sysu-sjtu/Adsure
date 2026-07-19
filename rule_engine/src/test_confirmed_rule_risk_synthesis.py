# -*- coding: utf-8 -*-
import unittest

from rule_engine import synthesize_confirmed_outcome


class ConfirmedRuleRiskSynthesisTests(unittest.TestCase):
    def test_confirmed_violation_outranks_fact_verification(self):
        rules = [
            {
                "rule_uid": "RUID-GOOD",
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "risk_level": "高",
                "applicability_status": "confirmed_violation",
                "legal_attention": {"default_route": "legal_review_required"},
            },
            {
                "rule_uid": "RUID-COSM",
                "rule_id": "COSM-002",
                "risk_level": "高",
                "applicability_status": "needs_fact_verification",
                "missing_facts": ["产品注册备案类别"],
            },
        ]

        outcome = synthesize_confirmed_outcome(rules, llm_risk="高")

        self.assertEqual("违规修改", outcome["opinion_type"])
        self.assertEqual("高", outcome["risk"])
        self.assertEqual("法务", outcome["routing"])

    def test_raw_high_risk_candidate_cannot_create_medium_floor(self):
        outcome = synthesize_confirmed_outcome([], llm_risk="无明显风险")

        self.assertEqual("无明显风险", outcome["risk"])
        self.assertEqual("无明显风险", outcome["opinion_type"])
        self.assertEqual("运营", outcome["routing"])

    def test_fact_only_outcome_requests_materials(self):
        outcome = synthesize_confirmed_outcome(
            [
                {
                    "rule_uid": "RUID-COSM",
                    "rule_id": "COSM-002",
                    "risk_level": "高",
                    "applicability_status": "needs_fact_verification",
                    "missing_facts": ["产品注册备案类别"],
                }
            ],
            llm_risk="中",
        )

        self.assertEqual("需补资料", outcome["opinion_type"])
        self.assertEqual("中", outcome["risk"])


if __name__ == "__main__":
    unittest.main()
