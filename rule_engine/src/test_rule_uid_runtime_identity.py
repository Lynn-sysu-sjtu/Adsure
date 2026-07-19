# -*- coding: utf-8 -*-
"""Tests for UID-based runtime parent and catalog identity."""

import unittest

from catalog_rule_directory import build_catalog_directory
from rule_engine import _merge_recalled_rules


class RuleUidRuntimeIdentityTests(unittest.TestCase):
    def test_parent_merge_keeps_distinct_uids_with_same_legacy_id(self):
        first = {"rule_uid": "RUID-first", "rule_id": "DUP-001", "title": "first"}
        second = {"rule_uid": "RUID-second", "rule_id": "DUP-001", "title": "second"}

        merged = _merge_recalled_rules([(first, ["one"]), (second, ["two"])])

        self.assertEqual(["RUID-first", "RUID-second"], [rule["rule_uid"] for rule, _ in merged])

    def test_parent_merge_still_combines_scenarios_of_same_uid(self):
        first = {"rule_uid": "RUID-one", "rule_id": "DUP-001"}
        same_parent = {"rule_uid": "RUID-one", "rule_id": "DUP-001"}

        merged = _merge_recalled_rules([(first, ["scenario-a"]), (same_parent, ["scenario-b"])])

        self.assertEqual(1, len(merged))
        self.assertEqual(["scenario-a", "scenario-b"], merged[0][1])

    def test_catalog_directory_uses_uid_for_uniqueness_and_exposes_both_ids(self):
        def rule(uid, title):
            return {
                "rule_uid": uid,
                "rule_id": "DUP-001",
                "title": title,
                "dimension": "开放规则",
                "recall": {
                    "trigger_layer": "content",
                    "catalog_recall_enabled": True,
                    "catalog_text": title,
                    "catalog_group": "open",
                },
            }

        directory = build_catalog_directory([rule("RUID-first", "first"), rule("RUID-second", "second")])

        self.assertEqual(["RUID-first", "RUID-second"], [item["rule_uid"] for item in directory])
        self.assertEqual(["DUP-001", "DUP-001"], [item["rule_id"] for item in directory])


if __name__ == "__main__":
    unittest.main()
