from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from src.platform_rules import (
    DEFAULT_CATALOG_PATH,
    PlatformRuleRepository,
    validate_catalog,
    validate_precheck_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = (
    REPO_ROOT
    / "data"
    / "platform_rules"
    / "raw_text"
    / "xhs_juguang_public_search_snapshot_2026-08-29.json"
)
CASES_PATH = (
    REPO_ROOT
    / "data"
    / "audit_test_cases"
    / "xiaohongshu_juguang_pilot_cases.json"
)


class PlatformRulesTest(unittest.TestCase):
    def test_catalog_is_structurally_valid_and_not_production(self):
        catalog = json.loads(DEFAULT_CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate_catalog(catalog), [])
        self.assertEqual(catalog["catalog_status"], "pilot_not_production")
        self.assertFalse(
            any(rule["review_status"] == "approved" for rule in catalog["rules"])
        )
        self.assertTrue(
            all(rule["rule_id"].startswith("XHS-") for rule in catalog["rules"])
        )

    def test_source_snapshot_hashes_match_saved_excerpts(self):
        snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        for source in snapshot["sources"]:
            actual = hashlib.sha256(
                source["observed_excerpt"].encode("utf-8")
            ).hexdigest()
            self.assertEqual(actual, source["content_hash"])

    def test_production_mode_refuses_pilot_rules(self):
        repository = PlatformRuleRepository(DEFAULT_CATALOG_PATH)
        result, error = repository.precheck(
            {
                "industry": "美妆",
                "platform": ["小红书"],
                "platform_scene": "聚光",
                "material_type": "图文",
                "content": "温和保湿",
            }
        )
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        precheck = result["platform_precheck"]
        self.assertEqual(precheck["coverage_status"], "rules_unavailable")
        self.assertEqual(precheck["verdict"], "manual_review_required")
        self.assertFalse(precheck["production_ready"])

    def test_pilot_regression_cases(self):
        repository = PlatformRuleRepository(
            DEFAULT_CATALOG_PATH,
            allow_pilot_rules=True,
        )
        cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                result, error = repository.precheck(case["input_payload"])
                self.assertIsNone(error)
                self.assertIsNotNone(result)
                precheck = result["platform_precheck"]
                expected = case["expected"]
                self.assertEqual(precheck["verdict"], expected["verdict"])
                if "coverage_status" in expected:
                    self.assertEqual(
                        precheck["coverage_status"],
                        expected["coverage_status"],
                    )
                actual_rule_ids = {
                    finding["rule_id"] for finding in precheck["findings"]
                }
                if "rule_ids" in expected:
                    self.assertEqual(actual_rule_ids, set(expected["rule_ids"]))
                if "unchecked_contains" in expected:
                    self.assertIn(
                        expected["unchecked_contains"],
                        precheck["unchecked_materials"],
                    )
                self.assertIn("仅为发布前预检", result["审核_平台规则预检"])

    def test_finding_retains_source_and_evidence_location(self):
        repository = PlatformRuleRepository(
            DEFAULT_CATALOG_PATH,
            allow_pilot_rules=True,
        )
        result, error = repository.precheck(
            {
                "industry": "保健食品",
                "product_category": "普通食品",
                "platform": ["小红书"],
                "platform_scene": "聚光",
                "material_type": "图文",
                "content": "清爽口感",
                "assets": [
                    {
                        "asset_id": "cover",
                        "type": "image",
                        "analysis_status": "completed",
                        "extracted_text": "辅助降血压",
                    }
                ],
                "has_landing_page": False,
            }
        )
        self.assertIsNone(error)
        finding = result["platform_precheck"]["findings"][0]
        self.assertEqual(finding["evidence"][0]["asset_id"], "cover")
        self.assertEqual(finding["evidence"][0]["matched_text"], "降血压")
        self.assertTrue(finding["source"]["source_url"].startswith("https://"))
        self.assertTrue(finding["source"]["raw_text_path"].endswith(".json"))

    def test_payload_rejects_non_xiaohongshu_request(self):
        payload, error = validate_precheck_payload(
            {
                "industry": "通用",
                "platform": ["抖音"],
                "material_type": "图文",
                "content": "测试",
            }
        )
        self.assertIsNone(payload)
        self.assertEqual(error, "platform 必须包含小红书")


if __name__ == "__main__":
    unittest.main()
