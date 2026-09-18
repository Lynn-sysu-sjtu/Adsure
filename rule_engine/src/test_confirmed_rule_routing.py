# -*- coding: utf-8 -*-
import unittest

from rule_engine import synthesize_confirmed_outcome


class ConfirmedRuleRoutingTests(unittest.TestCase):
    def test_rejected_legal_candidate_does_not_force_legal_route(self):
        final_rules = [
            {
                "rule_uid": "RUID-FACT",
                "rule_id": "FACT-001",
                "risk_level": "中",
                "applicability_status": "needs_fact_verification",
                "legal_attention": {"default_route": "operator_direct"},
                "missing_facts": ["证明材料"],
            }
        ]

        outcome = synthesize_confirmed_outcome(final_rules, llm_risk="中")

        self.assertEqual("运营", outcome["routing"])

    def test_primary_operator_direct_beats_secondary_legal_review(self):
        final_rules = [
            {
                "rule_uid": "RUID-OPERATOR",
                "rule_id": "HF-001-001",
                "risk_level": "高",
                "applicability_status": "confirmed_violation",
                "legal_attention": {
                    "default_route": "operator_direct",
                    "operator_fixability": "direct_fixable",
                    "trigger_clarity": "clear",
                    "legal_interpretation_level": "low",
                },
                "rule_applicability": {"type": "明确适用型"},
            },
            {
                "rule_uid": "RUID-LEGAL",
                "rule_id": "GEN-FALSE-001",
                "risk_level": "高",
                "applicability_status": "confirmed_violation",
                "legal_attention": {
                    "default_route": "legal_review_required",
                    "operator_fixability": "not_self_fixable",
                    "trigger_clarity": "open",
                    "legal_interpretation_level": "high",
                },
                "rule_applicability": {"type": "开放解释型"},
            },
        ]

        outcome = synthesize_confirmed_outcome(final_rules, llm_risk="高")

        self.assertEqual("运营", outcome["routing"])
        self.assertEqual("RUID-OPERATOR", outcome["routing_rule_uid"])
        self.assertEqual("primary_confirmed_rule", outcome["routing_reason"])

    def test_only_legal_review_rule_routes_legal(self):
        final_rules = [
            {
                "rule_uid": "RUID-LEGAL",
                "rule_id": "GEN-FALSE-001",
                "risk_level": "高",
                "applicability_status": "confirmed_violation",
                "legal_attention": {
                    "default_route": "legal_review_required",
                    "operator_fixability": "not_self_fixable",
                    "trigger_clarity": "open",
                    "legal_interpretation_level": "high",
                },
                "rule_applicability": {"type": "开放解释型"},
            }
        ]

        outcome = synthesize_confirmed_outcome(final_rules, llm_risk="高")

        self.assertEqual("法务", outcome["routing"])
        self.assertEqual("RUID-LEGAL", outcome["routing_rule_uid"])

    def test_fact_verification_routes_operator_first(self):
        final_rules = [
            {
                "rule_uid": "RUID-FACT-LEGAL",
                "rule_id": "HF-REG-001",
                "risk_level": "高",
                "applicability_status": "needs_fact_verification",
                "legal_attention": {
                    "default_route": "legal_review_required",
                    "operator_fixability": "not_self_fixable",
                    "trigger_clarity": "contextual",
                    "legal_interpretation_level": "medium",
                },
                "missing_facts": ["注册或备案材料"],
            }
        ]

        outcome = synthesize_confirmed_outcome(final_rules, llm_risk="高")

        self.assertEqual("运营", outcome["routing"])
        self.assertEqual("fact_verification_operator_first", outcome["routing_reason"])

    def test_guided_fixable_routes_operator(self):
        final_rules = [
            {
                "rule_uid": "RUID-DATA",
                "rule_id": "GEN-DATA-001",
                "risk_level": "中",
                "applicability_status": "confirmed_violation",
                "legal_attention": {
                    "default_route": "operator_supply_docs",
                    "operator_fixability": "guided_fixable",
                    "trigger_clarity": "contextual",
                    "legal_interpretation_level": "medium",
                },
                "rule_applicability": {"type": "关系判断型"},
            }
        ]

        outcome = synthesize_confirmed_outcome(final_rules, llm_risk="中")

        self.assertEqual("运营", outcome["routing"])
        self.assertEqual("RUID-DATA", outcome["routing_rule_uid"])


if __name__ == "__main__":
    unittest.main()
