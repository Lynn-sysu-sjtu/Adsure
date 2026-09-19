# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from kg_rule_store import load_rule_library
from rule_identity import rule_identity


class RuleUidRuntimeContractTests(unittest.TestCase):
    def _load_rules(self, rules):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base_dir = Path(temporary.name)
        jsonbase_dir = base_dir / "jsonbase"
        jsonbase_dir.mkdir()
        (jsonbase_dir / "rules.json").write_text(
            json.dumps({"rules": rules}, ensure_ascii=False),
            encoding="utf-8",
        )
        return load_rule_library(base_dir)

    def test_rule_identity_does_not_fall_back_to_legacy_rule_id(self):
        self.assertIsNone(rule_identity({"rule_id": "LEGACY-001"}))

    def test_loader_rejects_missing_rule_uid(self):
        with self.assertRaisesRegex(ValueError, "missing rule_uid"):
            self._load_rules([{"rule_id": "LEGACY-001"}])

    def test_loader_rejects_malformed_rule_uid(self):
        with self.assertRaisesRegex(ValueError, "invalid rule_uid"):
            self._load_rules(
                [{"rule_uid": "NOT-A-RUNTIME-UID", "rule_id": "LEGACY-001"}]
            )

    def test_loader_rejects_duplicate_rule_uid(self):
        with self.assertRaisesRegex(ValueError, "duplicate rule_uid"):
            self._load_rules(
                [
                    {"rule_uid": "RUID-SHARED", "rule_id": "LEGACY-001"},
                    {"rule_uid": "RUID-SHARED", "rule_id": "LEGACY-002"},
                ]
            )

    def test_loader_allows_duplicate_legacy_rule_id_when_uids_differ(self):
        library = self._load_rules(
            [
                {"rule_uid": "RUID-FIRST", "rule_id": "DUPLICATE-001"},
                {"rule_uid": "RUID-SECOND", "rule_id": "DUPLICATE-001"},
            ]
        )

        loaded_rules = library["data"]["rules"]
        self.assertEqual(
            ["RUID-FIRST", "RUID-SECOND"],
            [rule["rule_uid"] for rule in loaded_rules],
        )


if __name__ == "__main__":
    unittest.main()
