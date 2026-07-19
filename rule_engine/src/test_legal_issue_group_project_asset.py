# -*- coding: utf-8 -*-
"""Validation test for the checked-in legal issue group asset."""

import unittest
from pathlib import Path

from kg_rule_store import load_rule_library
from legal_issue_groups import load_legal_issue_groups, validate_legal_issue_groups


PROJECT_BASE = Path(__file__).resolve().parents[1]


class LegalIssueGroupProjectAssetTests(unittest.TestCase):
    def test_checked_in_group_asset_references_valid_single_layer_rules(self):
        rules = load_rule_library(PROJECT_BASE)["data"]["rules"]
        asset = load_legal_issue_groups(PROJECT_BASE)

        self.assertTrue(asset["groups"])
        self.assertTrue(validate_legal_issue_groups(asset, rules))


if __name__ == "__main__":
    unittest.main()
