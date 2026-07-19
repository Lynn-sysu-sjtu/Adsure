# -*- coding: utf-8 -*-
"""Tests for legal-issue group asset validation."""

import tempfile
import unittest
from pathlib import Path

from legal_issue_groups import load_legal_issue_groups, validate_legal_issue_groups


class LegalIssueGroupAssetTests(unittest.TestCase):
    def test_missing_asset_loads_as_empty_groups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual({"groups": []}, load_legal_issue_groups(Path(temp_dir)))

    def test_unknown_member_uid_is_rejected(self):
        asset = {"groups": [{"issue_group_id": "g1", "member_rule_uids": ["RUID-404"]}]}
        with self.assertRaisesRegex(ValueError, "RUID-404"):
            validate_legal_issue_groups(asset, [{"rule_uid": "RUID-ONE"}])

    def test_duplicate_group_ids_and_duplicate_membership_are_rejected(self):
        rules = [{"rule_uid": "RUID-ONE", "recall": {"trigger_layer": "content"}}]
        duplicate_group = {
            "groups": [
                {"issue_group_id": "g1", "member_rule_uids": ["RUID-ONE"]},
                {"issue_group_id": "g1", "member_rule_uids": []},
            ]
        }
        with self.assertRaisesRegex(ValueError, "g1"):
            validate_legal_issue_groups(duplicate_group, rules)

        duplicate_member = {
            "groups": [
                {"issue_group_id": "g1", "member_rule_uids": ["RUID-ONE"]},
                {"issue_group_id": "g2", "member_rule_uids": ["RUID-ONE"]},
            ]
        }
        with self.assertRaisesRegex(ValueError, "RUID-ONE"):
            validate_legal_issue_groups(duplicate_member, rules)

    def test_mixed_trigger_layers_are_rejected(self):
        rules = [
            {"rule_uid": "RUID-CONTENT", "recall": {"trigger_layer": "content"}},
            {"rule_uid": "RUID-FACT", "recall": {"trigger_layer": "fact"}},
        ]
        asset = {
            "groups": [
                {
                    "issue_group_id": "mixed",
                    "member_rule_uids": ["RUID-CONTENT", "RUID-FACT"],
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "trigger_layer"):
            validate_legal_issue_groups(asset, rules)


if __name__ == "__main__":
    unittest.main()
