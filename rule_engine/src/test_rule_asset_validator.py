# -*- coding: utf-8 -*-
"""Tests for deterministic validation of rule assets."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from kg_rule_store import load_rule_library
from rule_asset_validator import assert_valid_rule_assets, validate_rule_assets


class RuleAssetValidatorTests(unittest.TestCase):
    def test_reports_duplicate_rule_ids_with_sources_and_titles(self):
        report = validate_rule_assets(
            [
                {"rule_id": "DUP-001", "title": "规则B", "_source_file": "b.json"},
                {"rule_id": "DUP-001", "title": "规则A", "_source_file": "a.json"},
            ]
        )

        self.assertEqual(
            [
                {
                    "rule_id": "DUP-001",
                    "source_files": ["a.json", "b.json"],
                    "titles": ["规则A", "规则B"],
                }
            ],
            report["duplicate_rule_ids"],
        )

    def test_reports_empty_rule_ids_with_stable_locations(self):
        report = validate_rule_assets(
            [
                {"rule_id": " ", "title": "空规则B", "_source_file": "b.json"},
                {"title": "空规则A", "_source_file": "a.json"},
            ]
        )

        self.assertEqual(
            [
                {"source_file": "a.json", "title": "空规则A"},
                {"source_file": "b.json", "title": "空规则B"},
            ],
            report["empty_rule_ids"],
        )

    def test_reports_duplicate_scenario_ids_within_parent_only(self):
        report = validate_rule_assets(
            [
                {
                    "rule_id": "RULE-002",
                    "title": "规则二",
                    "_source_file": "b.json",
                    "recall": {
                        "semantic_scenarios": [
                            {"scenario_id": "same"},
                            {"scenario_id": "same"},
                        ]
                    },
                },
                {
                    "rule_id": "RULE-001",
                    "title": "规则一",
                    "_source_file": "a.json",
                    "recall": {"semantic_scenarios": [{"scenario_id": "same"}]},
                },
            ]
        )

        self.assertEqual(
            [
                {
                    "rule_id": "RULE-002",
                    "scenario_id": "same",
                    "source_file": "b.json",
                }
            ],
            report["duplicate_scenario_ids"],
        )

    def test_reports_each_orphan_reference_type_in_sorted_order(self):
        report = validate_rule_assets(
            [{"rule_id": "RULE-001", "title": "规则", "_source_file": "a.json"}],
            vector_rule_ids={"VECTOR-Z", "RULE-001", "VECTOR-A"},
            expected_rule_ids={"CASE-Z", "CASE-A"},
            group_rule_ids={"GROUP-Z", "GROUP-A"},
        )

        self.assertEqual(["VECTOR-A", "VECTOR-Z"], report["orphan_vector_rule_ids"])
        self.assertEqual(["CASE-A", "CASE-Z"], report["orphan_test_expected_rule_ids"])
        self.assertEqual(["GROUP-A", "GROUP-Z"], report["orphan_group_rule_ids"])

    def test_validation_does_not_mutate_input_rules(self):
        rules = [
            {
                "rule_id": "RULE-001",
                "_source_file": "a.json",
                "recall": {"semantic_scenarios": [{"scenario_id": "one"}]},
            }
        ]
        before = copy.deepcopy(rules)

        validate_rule_assets(rules)

        self.assertEqual(before, rules)

    def test_assert_valid_rule_assets_raises_with_unicode_json_details(self):
        report = {
            "duplicate_rule_ids": [],
            "empty_rule_ids": [{"source_file": "规则.json", "title": "空规则"}],
            "duplicate_scenario_ids": [],
            "orphan_vector_rule_ids": [],
            "orphan_test_expected_rule_ids": [],
            "orphan_group_rule_ids": [],
        }

        with self.assertRaisesRegex(ValueError, "规则.json"):
            assert_valid_rule_assets(report)

    def test_rule_library_validation_is_opt_in_and_fails_fast(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            jsonbase = Path(temp_dir) / "jsonbase"
            jsonbase.mkdir()
            for filename, title in (("a.json", "规则A"), ("b.json", "规则B")):
                (jsonbase / filename).write_text(
                    json.dumps(
                        {"legal_sources": [], "rules": [{"rule_id": "DUP-001", "title": title}]},
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            self.assertEqual(2, load_rule_library(temp_dir)["data"]["meta"]["rule_count"])
            with self.assertRaisesRegex(ValueError, "DUP-001"):
                load_rule_library(temp_dir, validate_assets=True)


if __name__ == "__main__":
    unittest.main()
