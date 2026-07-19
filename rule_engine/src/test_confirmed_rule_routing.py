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


if __name__ == "__main__":
    unittest.main()
