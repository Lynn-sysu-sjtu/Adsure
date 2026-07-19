import json
import unittest
from pathlib import Path

from catalog_rule_directory import build_catalog_directory


PROJECT_BASE = Path(__file__).resolve().parents[1]
AD_LAW_PATH = PROJECT_BASE / "jsonbase" / "20260623_中华人民共和国广告法_通用规则_v1.json"

EXPECTED_RULE_IDS = {
    "GEN-PUBLIC-INTEREST-001",
    "GEN-SAFETY-PRIVACY-001",
    "GEN-GOOD-CUSTOMS-001",
    "GEN-OBSCENE-VIOLENCE-001",
    "GEN-DISCRIMINATION-001",
    "GEN-ENV-CULTURE-001",
    "GEN-MINOR-HEALTH-001",
    "GEN-MINOR-INDUCEMENT-001",
}


class CatalogRuleDirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = json.loads(AD_LAW_PATH.read_text(encoding="utf-8-sig"))
        cls.rules = document["rules"]

    def test_only_approved_open_ended_rules_enter_catalog(self):
        directory = build_catalog_directory(
            self.rules,
            {"context": {"industry": "通用", "platforms": []}},
        )

        self.assertEqual(EXPECTED_RULE_IDS, {item["rule_id"] for item in directory})
        self.assertEqual(len(directory), len({item["rule_id"] for item in directory}))

    def test_catalog_entries_are_short_content_rules(self):
        directory = build_catalog_directory(self.rules, {})

        for item in directory:
            self.assertTrue(item["catalog_text"], item["rule_id"])
            self.assertLessEqual(len(item["catalog_text"]), 80, item["rule_id"])
            self.assertTrue(item["catalog_group"], item["rule_id"])
            self.assertEqual("content", item["trigger_layer"], item["rule_id"])

    def test_directory_exposes_only_fields_needed_by_catalog_model(self):
        directory = build_catalog_directory(self.rules, {})

        self.assertEqual(
            {"rule_id", "title", "dimension", "catalog_text", "catalog_group", "trigger_layer"},
            set(directory[0]),
        )


if __name__ == "__main__":
    unittest.main()
