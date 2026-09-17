# -*- coding: utf-8 -*-
import unittest

from catalog_rule_directory import build_catalog_directory
from rule_engine import build_context_package, fact_recall_rules, recall_rules
from semantic_recall import _rule_filter_reasons, semantic_recall_rules


def _request(platforms):
    return {
        "material": {"content": "销量数据突破100万，获得权威媒体报道"},
        "context": {
            "industry": "美妆",
            "platforms": platforms,
            "material_type": "图文文案",
            "product_category": "护肤",
            "core_claims": [],
        },
    }


def _platform_rule(trigger_layer="content"):
    return {
        "rule_id": "XHS-COSM-TEST-001",
        "rule_uid": "RUID-platform-gate-test",
        "serial_no": 1,
        "title": "事实性描述需要证明材料",
        "dimension": "事实核验",
        "risk_level": "中",
        "industry": "美妆",
        "source_type": "平台规则",
        "platform": "小红书",
        "applies_to": {
            "industries": ["美妆"],
            "platforms": ["小红书"],
            "material_types": ["图文文案"],
            "product_categories": ["护肤"],
        },
        "detection": {
            "keyword_signals": {"hit_terms": ["销量数据"]},
        },
        "recall": {
            "trigger_layer": trigger_layer,
            "semantic_enabled": True,
            "semantic_role": "primary",
            "vector_text": "销量数据突破100万，获得权威媒体报道",
            "catalog_recall_enabled": True,
            "catalog_text": "事实性描述需要证明材料",
            "catalog_group": "事实证明",
        },
        "preconditions": {"required_context_fields": ["proof_materials"]},
    }


class PlatformRecallGateTests(unittest.TestCase):
    def test_semantic_filter_reports_mismatched_platform(self):
        rule = _platform_rule()
        request = _request(["\u6296\u97f3"])

        reasons = _rule_filter_reasons(rule, request)

        self.assertIn("platform_scope_mismatch", reasons)

    def test_keyword_recall_requires_selected_matching_platform(self):
        rule = _platform_rule()

        for platforms in ([], ["抖音"], ["淘宝"]):
            request = _request(platforms)
            recalled = recall_rules([rule], request)
            self.assertEqual([], recalled, platforms)

        request = _request(["抖音", "小红书"])
        recalled = recall_rules([rule], request)
        self.assertEqual([rule["rule_id"]], [item[0]["rule_id"] for item in recalled])

    def test_rule_without_platform_scope_remains_available(self):
        rule = _platform_rule()
        rule["rule_id"] = "GENERAL-TEST-001"
        rule["source_type"] = "法规"
        rule["platform"] = ""
        rule["applies_to"]["platforms"] = []

        recalled = recall_rules([rule], _request([]))

        self.assertEqual([rule["rule_id"]], [item[0]["rule_id"] for item in recalled])

    def test_semantic_recall_rejects_mismatched_platform(self):
        rule = _platform_rule()
        request = _request(["抖音"])

        recalled = semantic_recall_rules(
            [rule],
            request,
            build_context_package(request),
            threshold=0.0,
            limit=5,
        )

        self.assertEqual([], recalled)

    def test_fact_recall_rejects_mismatched_platform(self):
        rule = _platform_rule(trigger_layer="fact")
        request = _request(["淘宝"])

        recalled = fact_recall_rules([rule], request)

        self.assertEqual([], recalled)

    def test_catalog_directory_rejects_mismatched_or_missing_platform(self):
        rule = _platform_rule()

        self.assertEqual([], build_catalog_directory([rule], _request([])))
        self.assertEqual([], build_catalog_directory([rule], _request(["抖音"])))
        self.assertEqual(
            [rule["rule_id"]],
            [item["rule_id"] for item in build_catalog_directory([rule], _request(["小红书"]))],
        )


if __name__ == "__main__":
    unittest.main()
