# -*- coding: utf-8 -*-
"""Contracts for the remaining 30-case path and quota repair assets."""

import json
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
MAPPING_PATH = (
    BASE
    / "reports"
    / "approved_issue_tree_v03"
    / "approved_rule_issue_mapping_v0.2.json"
)


class RemainingPathQuotaAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mappings = json.loads(
            MAPPING_PATH.read_text(encoding="utf-8-sig")
        )["mappings"]
        cls.mapping_contracts = {
            (
                item["rule_uid"],
                item["issue_id"],
                item["mapping_type"],
            )
            for item in cls.mappings
        }

    def test_missing_expected_uids_have_narrow_reviewed_leaf_mappings(self):
        expected = {
            (
                "RUID-1e455acefad683e3",
                "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.DISEASE_TREATMENT_MEDICAL_CLAIM",
                "direct",
            ),
            (
                "RUID-b60852699e8ddd70",
                "CLAIM_EXPRESSION.ABSOLUTE.ABSOLUTE_SUPERLATIVE_TERMS",
                "direct",
            ),
            (
                "RUID-5b2a03e0fd190b3e",
                "EVIDENCE_FACT.DATA_CITATION.CITATION_LACKS_SOURCE_SCOPE_OR_VALIDITY",
                "fact_check",
            ),
            (
                "RUID-7bb3f201c1db1fd8",
                "MINORS_PUBLIC_ORDER.MINOR_PAYMENT.MINOR_ANTI_ADDICTION_CIRCUMVENTION",
                "direct",
            ),
        }
        self.assertTrue(expected.issubset(self.mapping_contracts))

    def test_game_data_evidence_rule_uses_actionable_fact_quota(self):
        expected = (
            "RUID-9ecf144ad28c1c77",
            "EVIDENCE_FACT.DATA_CITATION.CITATION_LACKS_EVIDENCE_OR_SCIENTIFIC_BASIS",
            "fact_check",
        )
        self.assertIn(expected, self.mapping_contracts)
        self.assertNotIn(
            (
                expected[0],
                expected[1],
                "proactive_check",
            ),
            self.mapping_contracts,
        )


if __name__ == "__main__":
    unittest.main()
