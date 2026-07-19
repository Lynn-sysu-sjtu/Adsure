# -*- coding: utf-8 -*-
"""Tests for deterministic, persisted rule UID generation."""

import copy
import unittest

from rule_uid_migration import (
    assign_missing_rule_uids,
    generate_rule_uid,
    rule_uid_seed,
)


class RuleUidMigrationTests(unittest.TestCase):
    def setUp(self):
        self.rule = {
            "_source_file": "美妆/source.json",
            "rule_id": "COSM-001",
            "title": "化妆品功效规则",
            "legal_basis": [
                {
                    "source_name": "化妆品监督管理条例",
                    "article": "第三条",
                    "text": "功效宣称应当有充分依据。",
                }
            ],
        }

    def test_seed_is_stable_for_equivalent_dictionary_order(self):
        reordered = {
            "legal_basis": [
                {
                    "text": "功效宣称应当有充分依据。",
                    "article": "第三条",
                    "source_name": "化妆品监督管理条例",
                }
            ],
            "title": "化妆品功效规则",
            "rule_id": "COSM-001",
            "_source_file": "美妆/source.json",
        }

        self.assertEqual(rule_uid_seed(self.rule), rule_uid_seed(reordered))

    def test_generated_uid_is_deterministic_and_has_expected_format(self):
        first = generate_rule_uid(self.rule)
        second = generate_rule_uid(copy.deepcopy(self.rule))

        self.assertEqual(first, second)
        self.assertRegex(first, r"^RUID-[0-9a-f]{16}$")

    def test_source_file_participates_in_identity(self):
        other = copy.deepcopy(self.rule)
        other["_source_file"] = "美妆/other.json"

        self.assertNotEqual(generate_rule_uid(self.rule), generate_rule_uid(other))

    def test_assigns_only_missing_uids_without_mutating_input(self):
        existing = copy.deepcopy(self.rule)
        existing["rule_uid"] = "RU-EXISTING"
        missing = copy.deepcopy(self.rule)
        missing["_source_file"] = "美妆/missing.json"
        rules = [existing, missing]
        before = copy.deepcopy(rules)

        migrated, changes = assign_missing_rule_uids(rules)

        self.assertEqual(before, rules)
        self.assertEqual("RU-EXISTING", migrated[0]["rule_uid"])
        self.assertRegex(migrated[1]["rule_uid"], r"^RUID-[0-9a-f]{16}$")
        self.assertEqual(1, len(changes))

    def test_assignment_is_idempotent(self):
        first, first_changes = assign_missing_rule_uids([self.rule])
        second, second_changes = assign_missing_rule_uids(first)

        self.assertEqual(first, second)
        self.assertEqual(1, len(first_changes))
        self.assertEqual([], second_changes)

    def test_rejects_generated_uid_collisions(self):
        another = copy.deepcopy(self.rule)
        another["_source_file"] = "美妆/another.json"

        with self.assertRaisesRegex(ValueError, "collision"):
            assign_missing_rule_uids(
                [self.rule, another],
                uid_factory=lambda rule: "RU-COLLISION",
            )


if __name__ == "__main__":
    unittest.main()
