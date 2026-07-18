import unittest
from pathlib import Path

from compare_recall_modes import compare_cases


PROJECT_BASE = Path(__file__).resolve().parents[1]


class CompareRecallModesTests(unittest.TestCase):
    def test_compare_cases_reports_semantic_noise_and_missing_expected(self):
        report = compare_cases(base_dir=PROJECT_BASE, fallback_supplement_threshold=0.04)

        self.assertEqual(25, report["summary"]["case_count"])
        self.assertGreaterEqual(report["summary"]["semantic_gain_count"], 0)
        self.assertGreater(report["summary"]["semantic_noise_count"], 0)

        semantic_case = next(item for item in report["cases"] if item["case_id"] == "CASE-SEM-003")
        self.assertIn("IAM-CLICK-001", semantic_case["expected_semantic_rule_ids"])
        self.assertIn("IAM-CLICK-001", semantic_case["semantic_missing_expected_ids"])
        self.assertGreaterEqual(len(semantic_case["semantic_noise_rule_ids"]), 1)

    def test_compare_cases_reports_rule_level_statistics(self):
        report = compare_cases(base_dir=PROJECT_BASE, fallback_supplement_threshold=0.04)
        stats = report["rule_stats"]

        self.assertIn("top_noise_rules", stats)
        self.assertIn("top_expected_hit_rules", stats)
        self.assertIn("per_rule_noise_detail", stats)
        self.assertIsInstance(stats["top_noise_rules"], list)
        self.assertIsInstance(stats["top_expected_hit_rules"], list)
        self.assertIsInstance(stats["per_rule_noise_detail"], dict)
        self.assertTrue(
            all("rule_id" in item and "count" in item for item in stats["top_noise_rules"])
        )

    def test_compare_cases_keeps_keyword_baseline_visible(self):
        report = compare_cases(base_dir=PROJECT_BASE, fallback_supplement_threshold=0.04)

        keyword_case = next(item for item in report["cases"] if item["case_id"] == "CASE-COSM-001")
        self.assertIn("GEN-ABS-001", keyword_case["keyword_rule_ids"])
        self.assertIn("GEN-FALSE-001", keyword_case["keyword_rule_ids"])
        self.assertEqual([], keyword_case["expected_semantic_rule_ids"])


if __name__ == "__main__":
    unittest.main()
