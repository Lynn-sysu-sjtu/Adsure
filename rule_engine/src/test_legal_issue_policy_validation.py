# -*- coding: utf-8 -*-
"""Tests for legal-issue group selection policy validation."""

import unittest

from legal_issue_groups import validate_legal_issue_groups


class LegalIssuePolicyValidationTests(unittest.TestCase):
    def test_rejects_unknown_selection_strategy(self):
        rules = [{"rule_uid": "RUID-ONE", "recall": {"trigger_layer": "content"}}]
        asset = {
            "groups": [
                {
                    "issue_group_id": "g1",
                    "member_rule_uids": ["RUID-ONE"],
                    "selection_policy": {
                        "primary_rule_strategy": "random",
                        "platform_rule_strategy": "all_platforms",
                        "max_primary_rules": 1,
                        "max_platform_rules": 1,
                    },
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "selection_policy"):
            validate_legal_issue_groups(asset, rules)

    def test_rejects_non_positive_rule_limits(self):
        rules = [{"rule_uid": "RUID-ONE", "recall": {"trigger_layer": "content"}}]
        asset = {
            "groups": [
                {
                    "issue_group_id": "g1",
                    "member_rule_uids": ["RUID-ONE"],
                    "selection_policy": {
                        "primary_rule_strategy": "highest_legal_authority",
                        "platform_rule_strategy": "current_platform_only",
                        "max_primary_rules": 0,
                        "max_platform_rules": 1,
                    },
                }
            ]
        }
        with self.assertRaisesRegex(ValueError, "max_primary_rules"):
            validate_legal_issue_groups(asset, rules)


if __name__ == "__main__":
    unittest.main()
