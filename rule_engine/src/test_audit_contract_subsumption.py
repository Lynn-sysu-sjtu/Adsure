# -*- coding: utf-8 -*-
import json
import unittest
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]


class AuditContractSubsumptionTests(unittest.TestCase):
    def setUp(self):
        path = PROJECT_BASE / "schema" / "audit_response_schema_v0.1.json"
        self.schema = json.loads(path.read_text(encoding="utf-8-sig"))

    def test_old_required_matched_rule_fields_remain_unchanged(self):
        item_schema = self.schema["properties"]["data"]["properties"]["matched_rules"]["items"]
        self.assertEqual(
            ["rule_id", "title", "dimension", "risk_level", "judgment", "match_reason"],
            item_schema["required"],
        )

    def test_subsumption_and_dual_id_fields_are_optional_and_typed(self):
        item_schema = self.schema["properties"]["data"]["properties"]["matched_rules"]["items"]
        properties = item_schema["properties"]
        for field in [
            "rule_uid",
            "applicability_status",
            "material_evidence",
            "satisfied_elements",
            "unsatisfied_elements",
            "missing_facts",
            "applicability_reason",
            "confidence",
        ]:
            self.assertIn(field, properties)
            self.assertNotIn(field, item_schema["required"])
        self.assertEqual(
            ["confirmed_violation", "needs_fact_verification"],
            properties["applicability_status"]["enum"],
        )

    def test_recommended_risk_accepts_no_obvious_risk(self):
        risk_schema = self.schema["properties"]["data"]["properties"]["审核_推荐风险等级"]
        self.assertIn("无明显风险", risk_schema["enum"])


if __name__ == "__main__":
    unittest.main()
