# -*- coding: utf-8 -*-
"""Contracts for mapping defects exposed by the affected-case rerun."""

import json
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
APPROVED = BASE / "reports" / "approved_issue_tree_v03"
ACTUAL_USE_LEAF = (
    "ENDORSEMENT.ACTUAL_USE_DUTY."
    "ENDORSER_RECOMMENDS_WITHOUT_ACTUAL_USE"
)


class RemainingMappingRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = json.loads(
            (APPROVED / "approved_issue_taxonomy_v0.2.json").read_text(
                encoding="utf-8-sig"
            )
        )
        cls.mapping_asset = json.loads(
            (APPROVED / "approved_rule_issue_mapping_v0.2.json").read_text(
                encoding="utf-8-sig"
            )
        )

    def test_actual_use_duty_has_level_three_leaf(self):
        nodes = {
            item["issue_id"]: item
            for item in self.taxonomy["nodes"]
        }
        self.assertEqual("directory", nodes["ENDORSEMENT.ACTUAL_USE_DUTY"]["node_type"])
        leaf = nodes[ACTUAL_USE_LEAF]
        self.assertEqual(3, leaf["level"])
        self.assertEqual("legal_issue", leaf["node_type"])
        self.assertEqual("ENDORSEMENT.ACTUAL_USE_DUTY", leaf["parent_issue_id"])

    def test_actual_use_rules_map_to_leaf_instead_of_non_leaf(self):
        actual_use = [
            item
            for item in self.mapping_asset["mappings"]
            if item.get("rule_uid") == "RUID-8c3736290884aeb7"
        ]
        self.assertEqual(1, len(actual_use))
        self.assertEqual(ACTUAL_USE_LEAF, actual_use[0]["issue_id"])
        self.assertEqual("direct", actual_use[0]["mapping_type"])

    def test_game_license_rule_uses_actionable_fact_quota(self):
        matches = [
            item
            for item in self.mapping_asset["mappings"]
            if item.get("rule_uid") == "RUID-58e192a8dddf575c"
        ]
        self.assertEqual(1, len(matches))
        self.assertEqual("fact_check", matches[0]["mapping_type"])


if __name__ == "__main__":
    unittest.main()
