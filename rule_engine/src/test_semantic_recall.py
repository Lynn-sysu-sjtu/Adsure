import json
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pathlib import Path

from field_mapper import map_feishu_payload
from rule_engine import audit, build_context_package, recall_rules
from semantic_recall import semantic_recall_diagnostics, semantic_recall_rules


PROJECT_BASE = Path(__file__).resolve().parents[1]


class SemanticRecallTests(unittest.TestCase):
    def test_semantic_recall_deduplicates_multiple_scenarios_to_parent_rule(self):
        request = {
            "material": {"content": "我们一降价，你还不是像狗一样跑过来"},
            "context": {"industry": "通用", "core_claims": [], "platforms": []},
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "rule_uid": "RUID-good-customs",
                "serial_no": 1,
                "industry": "通用",
                "applies_to": {"industries": ["通用"]},
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "primary",
                    "vector_text": "侮辱物化消费者，以人格贬损方式刺激购买",
                    "semantic_scenarios": [
                        {"scenario_id": "consumer_insult", "vector_text": "侮辱顾客贬低消费者人格"},
                        {"scenario_id": "consumer_dehumanization", "vector_text": "把顾客比作狗进行动物化羞辱"},
                    ],
                },
            }
        ]
        recalled = semantic_recall_rules(rules, request, context_package, threshold=0.01, limit=5)
        self.assertEqual(1, len(recalled))
        self.assertEqual("GEN-GOOD-CUSTOMS-001", recalled[0][0]["rule_id"])
        self.assertIn("scenario=consumer_dehumanization", recalled[0][1][0])

    def test_semantic_recall_respects_material_type_scope(self):
        request = {
            "material": {"content": "\u4e3b\u64ad\u53e3\u64ad\u4e0a\u94fe\u63a5\u62cd\u4e0b\u9886\u53d6\u4f18\u60e0"},
            "context": {
                "industry": "\u7f8e\u5986",
                "material_type": "\u56fe\u6587\u6587\u6848",
                "product_category": "\u62a4\u80a4",
                "channels": ["\u793e\u4ea4\u5e73\u53f0"],
            },
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "LIVE-ONLY-001",
                "industry": "\u901a\u7528",
                "applies_to": {
                    "industries": ["\u901a\u7528", "\u7f8e\u5986"],
                    "material_types": ["\u76f4\u64ad\u8bdd\u672f"],
                    "product_categories": ["\u901a\u7528"],
                    "channels": ["\u76f4\u64ad"],
                },
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "\u4e3b\u64ad\u53e3\u64ad\u76f4\u64ad\u5e26\u8d27\u4e0a\u94fe\u63a5\u62cd\u4e0b\u9886\u53d6\u4f18\u60e0",
                },
            }
        ]

        recalled = semantic_recall_rules(rules, request, context_package, threshold=0.04, limit=5)

        self.assertEqual([], recalled)

    def test_semantic_recall_respects_product_category_and_channel_scope(self):
        request = {
            "material": {"content": "\u8425\u517b\u8bfe\u5802\u4ecb\u7ecd\u540c\u6b3e\u8865\u5145\u65b9\u6848\uff0c\u53ef\u79c1\u4fe1\u4e86\u89e3"},
            "context": {
                "industry": "\u4fdd\u5065\u98df\u54c1",
                "material_type": "\u56fe\u6587\u6587\u6848",
                "product_category": "\u666e\u901a\u98df\u54c1",
                "channels": ["\u793e\u4ea4\u5e73\u53f0"],
            },
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "HF-CATEGORY-001",
                "industry": "\u4fdd\u5065\u98df\u54c1",
                "applies_to": {
                    "industries": ["\u4fdd\u5065\u98df\u54c1"],
                    "material_types": ["\u56fe\u6587\u6587\u6848"],
                    "product_categories": ["\u8425\u517b\u8865\u5145"],
                    "channels": ["\u793e\u4ea4\u5e73\u53f0"],
                },
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "\u8425\u517b\u8bfe\u5802\u4ecb\u7ecd\u4fdd\u5065\u98df\u54c1\u8865\u5145\u65b9\u6848\u79c1\u4fe1\u4e86\u89e3\u8d2d\u4e70",
                },
            }
        ]

        recalled = semantic_recall_rules(rules, request, context_package, threshold=0.04, limit=5)

        self.assertEqual([], recalled)

    def test_semantic_recall_respects_negative_signals(self):
        request = {
            "material": {"content": "\u666e\u901a\u62a4\u80a4\u5fc3\u5f97\u91cc\u653e\u5165\u624b\u5165\u53e3\uff0c\u6ca1\u6709\u5546\u4e1a\u5408\u4f5c\u8bf4\u660e"},
            "context": {
                "industry": "\u7f8e\u5986",
                "material_type": "\u56fe\u6587\u6587\u6848",
                "product_category": "\u62a4\u80a4",
                "channels": ["\u793e\u4ea4\u5e73\u53f0"],
            },
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "HEALTHSOFT-001",
                "industry": "\u901a\u7528",
                "applies_to": {
                    "industries": ["\u901a\u7528", "\u7f8e\u5986"],
                    "material_types": ["\u56fe\u6587\u6587\u6848"],
                    "product_categories": ["\u901a\u7528", "\u62a4\u80a4"],
                    "channels": ["\u793e\u4ea4\u5e73\u53f0"],
                },
                "detection": {
                    "keyword_signals": {"negative_signals": ["\u666e\u901a\u62a4\u80a4\u5fc3\u5f97"]}
                },
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "\u5065\u5eb7\u79d1\u666e\u517b\u751f\u77e5\u8bc6\u8425\u517b\u8bfe\u5802\u5305\u88c5\u4fdd\u5065\u98df\u54c1\u63a8\u5e7f\u6587\u672b\u8d2d\u4e70\u5165\u53e3",
                },
            }
        ]

        recalled = semantic_recall_rules(rules, request, context_package, threshold=0.04, limit=5)

        self.assertEqual([], recalled)

    def test_semantic_recall_uses_vector_text_when_enabled(self):
        request = map_feishu_payload(
            {
                "record_id": "rec_semantic_unit",
                "fields": {
                    "①运营·行业领域": "美妆",
                    "①运营·物料内容": "像朋友聊天一样分享我的变美秘密，链接放这里",
                    "①美妆·物料类型": "图文文案",
                    "①美妆·投放平台": ["小红书"],
                    "①美妆·产品品类": "护肤",
                    "①美妆·核心宣称功效": "提亮",
                },
            }
        )
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "SEM-IDENT-001",
                "industry": "通用",
                "applies_to": {"industries": ["通用", "美妆"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "种草分享体验推荐好物购物链接广告应当显著标明广告，软文导流需可识别",
                },
            },
            {
                "rule_id": "SEM-DISABLED-001",
                "industry": "通用",
                "applies_to": {"industries": ["通用", "美妆"]},
                "recall": {
                    "semantic_enabled": False,
                    "vector_text": "种草分享体验推荐好物购物链接广告应当显著标明广告",
                },
            },
        ]

        recalled = semantic_recall_rules(rules, request, context_package, threshold=0.04, limit=5)

        self.assertEqual(["SEM-IDENT-001"], [rule["rule_id"] for rule, _ in recalled])
        self.assertIn("semantic:", recalled[0][1][0])

    def test_semantic_recall_diagnostics_includes_rule_routing_metadata(self):
        request = {
            "material": {"content": "personal note with a shopping link and no ad disclosure"},
            "context": {"industry": "Any", "core_claims": [], "platforms": []},
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "SEM-IDENT-001",
                "serial_no": 1,
                "title": "Native ad disclosure",
                "dimension": "ad identification",
                "risk_level": "high",
                "applies_to": {"industries": ["Any"]},
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "fallback",
                    "vector_text": "personal note shopping link no ad disclosure",
                },
            }
        ]

        diagnostics = semantic_recall_diagnostics(
            rules,
            request,
            context_package,
            threshold=0.01,
            top_k=1,
        )

        candidate = diagnostics["top_candidates"][0]
        self.assertEqual("SEM-IDENT-001", candidate["rule_id"])
        self.assertEqual("content", candidate["trigger_layer"])
        self.assertEqual("fallback", candidate["semantic_role"])
        self.assertEqual("high", candidate["risk_level"])
        self.assertEqual("ad identification", candidate["dimension"])

    def test_rule_engine_adds_semantic_recall_when_keyword_recall_misses(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            jsonbase = base / "jsonbase"
            jsonbase.mkdir()
            (jsonbase / "rules.json").write_text(
                json.dumps(
                    {
                        "meta": {"name": "semantic test"},
                        "legal_sources": [],
                        "rules": [
                            {
                                "rule_id": "SEM-IDENT-001",
                                "serial_no": 1,
                                "title": "native ad should be identifiable",
                                "dimension": "ad identification",
                                "risk_level": "?",
                                "applies_to": {"industries": ["Any"]},
                                "detection": {"keyword_signals": {"hit_terms": []}},
                                "recall": {
                                    "trigger_layer": "content",
                                    "semantic_enabled": True,
                                    "semantic_role": "fallback",
                                    "vector_text": "shopping link recommendation post should clearly disclose advertising",
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            response = audit(
                {
                    "record_id": "rec_semantic_001",
                    "industry": "Any",
                    "content": "I share my personal favorite product and put the shopping link in comments",
                },
                base_dir=base,
            )

        self.assertEqual(0, response["code"])
        matched = response["data"]["matched_rules"]
        self.assertTrue(any(rule.get("recall_channel") == "semantic" for rule in matched))
        self.assertIn("semantic_recall", response["data"])

    def test_rule_engine_runs_semantic_recall_without_keyword_or_cue(self):
        request = {
            "material": {"content": "native article presented as personal experience without sponsorship label"},
            "context": {"industry": "Any", "core_claims": [], "platforms": []},
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "SEM-NATIVE-001",
                "serial_no": 1,
                "title": "Native ad disclosure",
                "dimension": "ad identification",
                "risk_level": "medium",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": []}},
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "fallback",
                    "vector_text": "native article presented as personal experience without sponsorship label",
                },
            }
        ]

        with patch.dict("os.environ", {"ADSURE_NO_KEYWORD_SEMANTIC_THRESHOLD": "0.04"}):
            recalled = recall_rules(rules, request, context_package=context_package)

        self.assertEqual(["SEM-NATIVE-001"], [rule["rule_id"] for rule, _ in recalled])
        self.assertTrue(any(hit.startswith("semantic") for _, hits in recalled for hit in hits))
    def test_rule_engine_allows_high_confidence_fallback_semantic_when_keyword_recall_succeeds(self):
        request = {
            "material": {"content": "hard keyword personal note shopping link no ad disclosure"},
            "context": {"industry": "Any", "core_claims": [], "platforms": []},
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "KEYWORD-001",
                "serial_no": 1,
                "risk_level": "medium",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": ["hard keyword"]}},
                "recall": {"trigger_layer": "content"},
            },
            {
                "rule_id": "SEM-FALLBACK-001",
                "serial_no": 2,
                "risk_level": "medium",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": []}},
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "fallback",
                    "vector_text": "personal note shopping link no ad disclosure",
                },
            },
        ]

        recalled = recall_rules(
            rules,
            request,
            context_package=context_package,
            semantic_limit=5,
            fallback_supplement_threshold=0.04,
            fallback_supplement_limit=1,
        )

        self.assertEqual(
            ["KEYWORD-001", "SEM-FALLBACK-001"],
            [rule["rule_id"] for rule, _ in recalled],
        )
        self.assertTrue(any(hit.startswith("semantic") for _, hits in recalled for hit in hits))
    def test_rule_engine_does_not_add_fallback_semantic_when_keyword_recall_succeeds(self):
        response = audit(
            {
                "record_id": "rec_semantic_guardrail",
                "mode": "标准",
                "fields": {
                    "①运营·行业领域": "美妆",
                    "①运营·物料内容": "今天分享真实体验，种草这款精华，购物链接放在评论区",
                    "①美妆·物料类型": "图文文案",
                    "①美妆·投放平台": ["小红书"],
                    "①美妆·产品品类": "护肤",
                    "①美妆·核心宣称功效": "提亮",
                },
            },
            base_dir=PROJECT_BASE,
        )

        self.assertEqual(0, response["code"])
        matched = response["data"]["matched_rules"]
        self.assertTrue(any(rule.get("recall_channel") == "keyword" for rule in matched))
        self.assertFalse(any(rule.get("recall_channel") == "semantic" for rule in matched))

    def test_rule_engine_uses_high_threshold_fallback_call_when_keyword_recall_succeeds(self):
        request = {
            "material": {"content": "????"},
            "context": {"industry": "??"},
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "GEN-ABS-001",
                "industry": "??",
                "risk_level": "?",
                "applies_to": {"industries": ["??", "??"]},
                "detection": {"keyword_signals": {"hit_terms": ["????"]}},
                "recall": {"semantic_enabled": True, "semantic_role": "fallback", "vector_text": "???????"},
            }
        ]

        with patch("rule_engine.semantic_recall_rules") as fake_semantic:
            recalled = recall_rules(rules, request, context_package=context_package)

        self.assertEqual(["GEN-ABS-001"], [rule["rule_id"] for rule, _ in recalled])
        fake_semantic.assert_called_once()
        _, _, kwargs = fake_semantic.mock_calls[0]
        self.assertEqual(0.10, kwargs.get("threshold"))
        self.assertEqual(2, kwargs.get("limit"))


if __name__ == "__main__":
    unittest.main()
