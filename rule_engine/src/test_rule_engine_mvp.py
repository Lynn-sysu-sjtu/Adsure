import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from audit_api import audit_endpoint
from field_mapper import map_feishu_payload
from rule_engine import (
    _card_hit_summary,
    _format_legal_basis_details,
    _high_risk_evidence_summary,
    _synthesize_risk_level,
    audit,
    build_context_package,
    fact_recall_rules,
    recall_rules,
)


BASE = Path(__file__).resolve().parents[1]


class RuleEngineMvpTests(unittest.TestCase):
    def test_audit_contract_schemas_are_valid_json(self):
        for filename in ["audit_request_schema_v0.1.json", "audit_response_schema_v0.1.json"]:
            path = BASE / "schema" / filename
            self.assertTrue(path.exists(), f"Missing {filename}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("object", payload["type"])
            self.assertIn("required", payload)

    def test_maps_feishu_fields_to_internal_request(self):
        request = map_feishu_payload(
            {
                "record_id": "rec_test_001",
                "mode": "极速",
                "fields": {
                    "①运营·物料编号": "AD-001",
                    "①运营·行业领域": "美妆",
                    "①运营·物料内容": [{"text": "15天焕发新生，全网第一"}],
                    "①运营·紧急程度": "紧急",
                    "①美妆·物料类型": "Banner",
                    "①美妆·投放平台": "抖音,小红书",
                    "①美妆·产品品类": "护肤",
                    "①美妆·产品备案名称": "某某精华液",
                    "①美妆·核心宣称功效": "提亮,改善肤色",
                    "①美妆·物料涉及场景": "新品推广",
                },
            }
        )

        self.assertEqual("rec_test_001", request["request_id"])
        self.assertEqual("AD-001", request["material"]["material_id"])
        self.assertEqual("15天焕发新生，全网第一", request["material"]["content"])
        self.assertEqual("美妆", request["context"]["industry"])
        self.assertEqual(["抖音", "小红书"], request["context"]["platforms"])
        self.assertEqual(["提亮", "改善肤色"], request["context"]["core_claims"])
        self.assertEqual("极速", request["audit"]["requested_mode"])

    def test_rule_engine_returns_standard_mvp_response(self):
        response = audit(
            {
                "record_id": "rec_test_002",
                "mode": "深度",
                "fields": {
                    "①运营·物料编号": "AD-002",
                    "①运营·行业领域": "美妆",
                    "①运营·物料内容": "15天见效，全网第一，焕发新生",
                    "①美妆·物料类型": "Banner",
                    "①美妆·投放平台": ["抖音"],
                    "①美妆·产品品类": "护肤",
                    "①美妆·核心宣称功效": "改善肤色",
                },
            },
            base_dir=BASE,
        )

        self.assertEqual(0, response["code"])
        data = response["data"]
        self.assertEqual("rec_test_002", data["request_id"])
        self.assertEqual("标准", data["resolved_mode"])
        self.assertGreaterEqual(len(data["matched_rules"]), 1)
        self.assertIn("审核_审核意见", data)
        self.assertIn(data["routing"], ["运营", "法务"])
        display_text = "\n".join(
            [
                data.get("预审_命中要点", ""),
                data.get("审核_高风险词命中", ""),
                data.get("审核_审核意见", ""),
                json.dumps(data.get("matched_rules", []), ensure_ascii=False),
            ]
        )
        self.assertNotIn("regex:", display_text)
        self.assertNotIn("????", display_text)

        for field in ("预审_命中要点", "审核_高风险词命中"):
            self.assertIsInstance(data[field], str)
            self.assertNotIn("[", data[field])
            self.assertNotIn("]", data[field])
            self.assertNotIn("regex:", data[field])

        self.assertTrue(any(rule.get("rule_id") for rule in data["matched_rules"]))
        self.assertIn("[", data["审核_审核意见"])

    def test_card_hit_summary_uses_plain_evidence_and_reason_without_rule_id(self):
        rules = [
            {
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "title": "广告不得妨碍公共秩序或违背社会良好风尚",
                "applicability_status": "confirmed_violation",
                "material_evidence": "和狗一样跑过来",
                "applicability_reason": (
                    "[GEN-GOOD-CUSTOMS-001] 将消费者作动物化贬损，"
                    "违背社会良好风尚。"
                ),
            }
        ]

        summary = _card_hit_summary(rules)

        self.assertIn("和狗一样跑过来", summary)
        self.assertIn("违背社会良好风尚", summary)
        self.assertNotIn("GEN-GOOD-CUSTOMS-001", summary)
        self.assertNotIn("[", summary)
        self.assertNotIn("]", summary)
        self.assertNotIn("regex:", summary)

    def test_card_summaries_keep_missing_facts_and_plain_original_evidence(self):
        rules = [
            {
                "rule_id": "GAME-FALSE-004",
                "title": "禁止虚假广告（虚构使用效果）",
                "applicability_status": "needs_fact_verification",
                "material_evidence": "开局十连抽，爆率拉满，神装随便出",
                "applicability_reason": "该表述可能使玩家形成高概率获得装备的预期。",
                "missing_facts": ["游戏实际奖池、概率、保底和适用条件资料"],
            }
        ]

        hit_summary = _card_hit_summary(rules)
        evidence_summary = _high_risk_evidence_summary(rules)

        self.assertIn("高概率", hit_summary)
        self.assertIn("游戏实际奖池、概率、保底和适用条件资料", hit_summary)
        self.assertEqual("开局十连抽，爆率拉满，神装随便出", evidence_summary)
        for value in (hit_summary, evidence_summary):
            self.assertNotIn("GAME-FALSE-004", value)
            self.assertNotIn("[", value)
            self.assertNotIn("]", value)
            self.assertNotIn("regex:", value)

    def test_audit_canonical_payload_returns_tenant_and_request_ids(self):
        response = audit(
            {
                "tenant_id": "tenant_example",
                "request_id": "req_canonical_001",
                "source": "internal",
                "material": {"content": "新品上市，欢迎选购"},
                "context": {
                    "industry": "美妆",
                    "platforms": ["抖音"],
                    "material_type": "Banner",
                    "product_category": "护肤",
                },
                "unknown_field": "ignored",
            },
            base_dir=BASE,
        )

        self.assertEqual(0, response["code"])
        self.assertEqual("tenant_example", response["data"]["tenant_id"])
        self.assertEqual("req_canonical_001", response["data"]["request_id"])
    def test_canonical_payload_missing_content_keeps_existing_error_contract(self):
        response = audit_endpoint(
            {
                "tenant_id": "adsure_demo",
                "request_id": "req_missing_content",
                "material": {"content": ""},
                "context": {"industry": "美妆"},
            }
        )

        self.assertEqual(-1, response["code"])
        self.assertEqual("缺少必填字段：①运营·物料内容", response["msg"])
        self.assertIsNone(response["data"])
    def test_audit_safe_content_routes_to_operator(self):
        response = audit(
            {
                "record_id": "rec_test_operator_001",
                "mode": "\u6807\u51c6",
                "industry": "\u7f8e\u5986",
                "content": "\u65b0\u54c1\u4e0a\u5e02\uff0c\u6b22\u8fce\u9009\u8d2d",
                "urgency": "\u666e\u901a",
                "supplement": "",
                "platform": ["\u6296\u97f3"],
                "material_type": "Banner",
                "product_category": "\u62a4\u80a4",
                "extras": {},
            },
            base_dir=BASE,
        )

        self.assertEqual(0, response["code"])
        data = response["data"]
        self.assertEqual("\u8fd0\u8425", data["routing"])
        self.assertEqual("\u65e0\u660e\u663e\u98ce\u9669", data["\u9884\u5ba1_\u98ce\u9669\u7b49\u7ea7"])
        self.assertEqual([], data["matched_rules"])

    def test_keyword_recall_ignores_material_type_context_terms(self):
        response = audit(
            {
                "record_id": "rec_live_context_only",
                "mode": "\u6807\u51c6",
                "industry": "\u7f8e\u5986",
                "content": "\u65b0\u54c1\u4e0a\u5e02\uff0c\u6b22\u8fce\u9009\u8d2d",
                "urgency": "\u666e\u901a",
                "supplement": "",
                "platform": ["\u6296\u97f3"],
                "material_type": "\u76f4\u64ad\u8bdd\u672f",
                "product_category": "\u62a4\u80a4",
                "extras": {},
            },
            base_dir=BASE,
        )

        self.assertEqual(0, response["code"])
        data = response["data"]
        self.assertEqual("\u8fd0\u8425", data["routing"])
        self.assertEqual("\u65e0\u660e\u663e\u98ce\u9669", data["\u9884\u5ba1_\u98ce\u9669\u7b49\u7ea7"])
        self.assertEqual("\u65e0\u660e\u663e\u547d\u4e2d", data["\u9884\u5ba1_\u547d\u4e2d\u8981\u70b9"])
        self.assertEqual([], data["matched_rules"])

    def test_weak_hit_terms_are_not_exposed_in_user_facing_output(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            jsonbase = base / "jsonbase"
            jsonbase.mkdir()
            (jsonbase / "rules.json").write_text(
                json.dumps(
                    {
                        "meta": {"name": "weak hit display test"},
                        "legal_sources": [
                            {
                                "id": "AL",
                                "name": "中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载",
                                "type": "法规",
                                "legal_level": 1,
                            }
                        ],
                        "rules": [
                            {
                                "rule_id": "GAME-GIFT-001",
                                "serial_no": 1,
                                "title": "游戏赠送福利需明示活动规则",
                                "dimension": "虚假宣传",
                                "risk_level": "中",
                                "applies_to": {"industries": ["游戏"]},
                                "detection": {"keyword_signals": {"hit_terms": ["送"]}},
                                "legal_basis": [
                                    {
                                        "source_id": "AL",
                                        "article": "第八条",
                                        "text": "广告中表明推销的商品或者服务附带赠送的，应当明示所附带赠送商品或者服务的品种、规格、数量、期限和方式。",
                                    }
                                ],
                                "recall": {"trigger_layer": "content"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            response = audit(
                {
                    "record_id": "rec_weak_hit_display",
                    "industry": "游戏",
                    "content": "充 3 元送一只狗",
                    "material_type": "Banner",
                    "product_category": "其他",
                },
                base_dir=base,
            )

        data = response["data"]
        user_facing_text = "\n".join(
            [
                data["预审_命中要点"],
                data["审核_高风险词命中"],
                data["审核_审核意见"],
                "\n".join(rule["match_reason"] for rule in data["matched_rules"]),
            ]
        )

        self.assertIn("[GAME-GIFT-001] 游戏赠送福利需明示活动规则", user_facing_text)
        self.assertIn("【触犯法条原文】", user_facing_text)
        self.assertIn("【法律】《中华人民共和国广告法》第八条：“广告中表明推销的商品或者服务附带赠送的", user_facing_text)
        self.assertNotIn("AL第八条", user_facing_text)
        self.assertNotIn("命中要点：送", user_facing_text)

    def test_legal_basis_details_show_authority_level_labels(self):
        section = _format_legal_basis_details(
            [
                {
                    "rule_id": "GEN-GIFT-001",
                    "title": "广告附赠应当明示",
                    "dimension": "虚假宣传",
                    "risk_level": "中",
                    "source_type": "法规",
                    "legal_basis_detail": [
                        {
                            "source_id": "AL",
                            "source_name": "中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载",
                            "article": "第八条",
                            "legal_level": 1,
                            "text": "广告中表明推销的商品或者服务附带赠送的，应当明示所附带赠送商品或者服务的品种、规格、数量、期限和方式。",
                        }
                    ],
                },
                {
                    "rule_id": "GAME-BILI-002",
                    "title": "涉及赠送活动需明示参与条件",
                    "dimension": "虚假宣传",
                    "risk_level": "中",
                    "source_type": "平台规则",
                    "legal_basis_detail": [
                        {
                            "source_id": "BILI",
                            "source_name": "B站广告推广平台审核规范（二）",
                            "article": "7.",
                            "text": "涉及赠送/送/免费等活动应当明示参与条件与门槛。",
                        }
                    ],
                },
            ]
        )

        self.assertIn("【法律】《中华人民共和国广告法》第八条：“广告中表明推销的商品或者服务附带赠送的", section)
        self.assertIn("【平台规则】《B站广告推广平台审核规范（二）》7.：“涉及赠送/送/免费等活动应当明示参与条件与门槛", section)
        self.assertNotIn("[GEN-GIFT-001]", section)
        self.assertNotIn("AL第八条", section)

    def test_plain_copy_recall_only_uses_content_trigger_layer(self):
        request = {
            "material": {"content": "magicword ultimate promise"},
            "context": {"industry": "Any", "core_claims": [], "platforms": []},
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "CONTENT-001",
                "serial_no": 1,
                "risk_level": "high",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": ["magicword"]}},
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "primary",
                    "vector_text": "ultimate promise",
                },
            },
            {
                "rule_id": "FACT-001",
                "serial_no": 2,
                "risk_level": "high",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": ["magicword"]}},
                "recall": {
                    "trigger_layer": "fact",
                    "semantic_enabled": True,
                    "semantic_role": "primary",
                    "vector_text": "ultimate promise",
                },
            },
            {
                "rule_id": "WORKFLOW-001",
                "serial_no": 3,
                "risk_level": "high",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": ["magicword"]}},
                "recall": {
                    "trigger_layer": "workflow",
                    "semantic_enabled": True,
                    "semantic_role": "primary",
                    "vector_text": "ultimate promise",
                },
            },
        ]

        recalled = recall_rules(rules, request, context_package=context_package)

        self.assertEqual(["CONTENT-001"], [rule["rule_id"] for rule, _ in recalled])
    def test_keyword_priority_keeps_important_rules_inside_limited_candidate_pool(self):
        request = {
            "material": {"content": "shared keyword"},
            "context": {"industry": "Any", "core_claims": [], "platforms": []},
        }
        rules = [
            {
                "rule_id": f"HIGH-{index}",
                "serial_no": index,
                "risk_level": "\u9ad8",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": ["shared"]}},
                "recall": {"trigger_layer": "content"},
            }
            for index in range(1, 8)
        ]
        rules.append(
            {
                "rule_id": "IMPORTANT-LIVE-ENDORSE",
                "serial_no": 99,
                "risk_level": "\u4e2d",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": ["shared"]}},
                "recall": {"trigger_layer": "content", "keyword_priority": 100},
            }
        )

        recalled = recall_rules(rules, request, keyword_limit=3)

        self.assertIn("IMPORTANT-LIVE-ENDORSE", [rule["rule_id"] for rule, _ in recalled])
    def test_risk_synthesis_can_lower_operator_fixable_high_rule_to_llm_medium(self):
        final, source, reason = _synthesize_risk_level(
            "高",
            "中",
            [
                {
                    "rule_id": "CLEAR-HIGH-001",
                    "risk_level": "高",
                    "legal_attention": {
                        "default_route": "operator_direct",
                        "operator_fixability": "direct_fixable",
                    },
                }
            ],
        )

        self.assertEqual("中", final)
        self.assertEqual("llm_case_adjusted", source)
        self.assertIn("个案", reason)

    def test_risk_synthesis_uses_llm_medium_even_for_legal_review_rules(self):
        final, source, reason = _synthesize_risk_level(
            "高",
            "中",
            [
                {
                    "rule_id": "HARD-LEGAL-001",
                    "risk_level": "高",
                    "legal_attention": {
                        "default_route": "legal_review_required",
                        "risk_severity": "high",
                        "legal_interpretation_level": "high",
                        "operator_fixability": "not_self_fixable",
                    },
                }
            ],
        )

        self.assertEqual("中", final)
        self.assertEqual("llm_case_adjusted", source)
        self.assertIn("个案", reason)

    def test_risk_synthesis_keeps_at_least_medium_when_rule_matches_but_llm_says_none(self):
        final, source, reason = _synthesize_risk_level(
            "高",
            "无明显风险",
            [
                {
                    "rule_id": "SUPPLY-DOCS-001",
                    "risk_level": "高",
                    "legal_attention": {"default_route": "operator_supply_docs"},
                }
            ],
        )

        self.assertEqual("中", final)
        self.assertEqual("minimum_matched_risk", source)
        self.assertIn("至少保留中风险", reason)
    def test_matched_rules_include_diagnostic_rule_metadata(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            jsonbase = base / "jsonbase"
            jsonbase.mkdir()
            (jsonbase / "rules.json").write_text(
                json.dumps(
                    {
                        "meta": {"name": "diagnostic metadata test"},
                        "legal_sources": [
                            {
                                "id": "AL",
                                "name": "中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载",
                                "type": "法规",
                                "legal_level": 1,
                            }
                        ],
                        "rules": [
                            {
                                "rule_id": "DIAG-001",
                                "rule_uid": "RUID-diagnostic-001",
                                "serial_no": 1,
                                "title": "Diagnostic metadata rule",
                                "dimension": "诊断字段",
                                "risk_level": "中",
                                "applies_to": {"industries": ["Any"]},
                                "detection": {"keyword_signals": {"hit_terms": ["diagnosticword"]}},
                                "recall": {"trigger_layer": "content"},
                                "legal_attention": {"default_route": "operator_direct"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            response = audit(
                {
                    "record_id": "rec_diagnostic_metadata",
                    "industry": "Any",
                    "content": "This copy contains diagnosticword.",
                },
                base_dir=base,
            )

        self.assertEqual(0, response["code"])
        matched = response["data"]["matched_rules"][0]
        self.assertEqual("RUID-diagnostic-001", matched["rule_uid"])
        self.assertEqual("content", matched["trigger_layer"])
        self.assertEqual("operator_direct", matched["legal_attention"]["default_route"])
    def test_legal_attention_operator_direct_overrides_high_risk_routing(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            jsonbase = base / "jsonbase"
            jsonbase.mkdir()
            (jsonbase / "rules.json").write_text(
                json.dumps(
                    {
                        "meta": {"name": "legal attention routing test"},
                        "legal_sources": [
                            {
                                "id": "AL",
                                "name": "中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载",
                                "type": "法规",
                                "legal_level": 1,
                            }
                        ],
                        "rules": [
                            {
                                "rule_id": "CONTENT-HIGH-OPERATOR-001",
                                "serial_no": 1,
                                "title": "Clear high-risk copy issue",
                                "dimension": "copy issue",
                                "risk_level": "\u9ad8",
                                "applies_to": {"industries": ["Any"]},
                                "detection": {"keyword_signals": {"hit_terms": ["forbiddenword"]}},
                                "recall": {"trigger_layer": "content"},
                                "legal_attention": {
                                    "default_route": "operator_direct",
                                    "operator_fixability": "direct_fixable",
                                    "calibration_status": "provisional",
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
                    "record_id": "rec_legal_attention_operator",
                    "industry": "Any",
                    "content": "This copy contains forbiddenword.",
                },
                base_dir=base,
            )

        self.assertEqual(0, response["code"])
        self.assertEqual("\u8fd0\u8425", response["data"]["routing"])

    def test_legal_attention_legal_review_required_routes_to_legal(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            jsonbase = base / "jsonbase"
            jsonbase.mkdir()
            (jsonbase / "rules.json").write_text(
                json.dumps(
                    {
                        "meta": {"name": "legal attention routing test"},
                        "legal_sources": [
                            {
                                "id": "AL",
                                "name": "中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载",
                                "type": "法规",
                                "legal_level": 1,
                            }
                        ],
                        "rules": [
                            {
                                "rule_id": "CONTENT-LEGAL-001",
                                "serial_no": 1,
                                "title": "Open legal concept",
                                "dimension": "open concept",
                                "risk_level": "\u4e2d",
                                "applies_to": {"industries": ["Any"]},
                                "detection": {"keyword_signals": {"hit_terms": ["softclaim"]}},
                                "recall": {"trigger_layer": "content"},
                                "legal_attention": {
                                    "default_route": "legal_review_required",
                                    "legal_interpretation_level": "high",
                                    "calibration_status": "provisional",
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
                    "record_id": "rec_legal_attention_legal",
                    "industry": "Any",
                    "content": "This copy contains softclaim.",
                },
                base_dir=base,
            )

        self.assertEqual(0, response["code"])
        self.assertEqual("\u6cd5\u52a1", response["data"]["routing"])
    def test_fact_recall_uses_existing_output_fields_for_supplement_request(self):
        request = {
            "request_id": "rec_fact_001",
            "material": {"content": "This ad claims patented technology and official certification."},
            "context": {"industry": "Any", "core_claims": [], "platforms": []},
        }
        context_package = build_context_package(request)
        rules = [
            {
                "rule_id": "FACT-PATENT-001",
                "serial_no": 1,
                "title": "Patent claim requires proof materials",
                "dimension": "fact verification",
                "risk_level": "medium",
                "applies_to": {"industries": ["Any"]},
                "preconditions": {"required_context_fields": ["approval_or_filing_number"]},
                "detection": {"keyword_signals": {"hit_terms": ["patented"]}},
                "recall": {"trigger_layer": "fact"},
            },
            {
                "rule_id": "WORKFLOW-001",
                "serial_no": 2,
                "title": "Archive duty",
                "dimension": "workflow",
                "risk_level": "high",
                "applies_to": {"industries": ["Any"]},
                "detection": {"keyword_signals": {"hit_terms": ["patented"]}},
                "recall": {"trigger_layer": "workflow"},
            },
        ]

        fact_recalled = fact_recall_rules(rules, request, context_package=context_package)

        self.assertEqual(["FACT-PATENT-001"], [rule["rule_id"] for rule, _ in fact_recalled])
        self.assertTrue(any(str(hit).startswith("fact_missing_context:") for _, hits in fact_recalled for hit in hits))
    def test_fact_recall_uses_chinese_fact_claim_terms(self):
        request = {
            "material": {"content": "\u672c\u4ea7\u54c1\u91c7\u7528\u4e13\u5229\u6280\u672f\u5e76\u53d6\u5f97\u5b98\u65b9\u8ba4\u8bc1"},
            "context": {"industry": "Any", "core_claims": [], "platforms": []},
        }
        rules = [
            {
                "rule_id": "FACT-ZH-001",
                "serial_no": 1,
                "title": "\u4e13\u5229\u6216\u8ba4\u8bc1\u5ba3\u79f0\u9700\u8865\u5145\u8bc1\u660e",
                "dimension": "\u4e8b\u5b9e\u6838\u9a8c",
                "risk_level": "\u4e2d",
                "applies_to": {"industries": ["Any"]},
                "preconditions": {"required_context_fields": ["approval_or_filing_number"]},
                "detection": {"keyword_signals": {"hit_terms": []}},
                "recall": {"trigger_layer": "fact"},
            }
        ]

        fact_recalled = fact_recall_rules(rules, request)

        self.assertEqual(["FACT-ZH-001"], [rule["rule_id"] for rule, _ in fact_recalled])
        self.assertTrue(any(hit == "fact_claim:\u4e13\u5229" for _, hits in fact_recalled for hit in hits))

    def test_audit_fact_only_case_returns_supplement_request_without_new_interface(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            jsonbase = base / "jsonbase"
            jsonbase.mkdir()
            (jsonbase / "rules.json").write_text(
                json.dumps(
                    {
                        "meta": {"name": "fact test"},
                        "legal_sources": [],
                        "rules": [
                            {
                                "rule_id": "FACT-PATENT-001",
                                "serial_no": 1,
                                "title": "Patent claim requires proof materials",
                                "dimension": "fact verification",
                                "risk_level": "中",
                                "applies_to": {"industries": ["Any"]},
                                "preconditions": {"required_context_fields": ["approval_or_filing_number"]},
                                "detection": {"keyword_signals": {"hit_terms": ["patented"]}},
                                "recall": {"trigger_layer": "fact"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            response = audit(
                {
                    "record_id": "rec_fact_002",
                    "industry": "Any",
                    "content": "This ad claims patented technology and official certification.",
                },
                base_dir=base,
            )

        data = response["data"]
        self.assertEqual(0, response["code"])
        self.assertEqual("运营", data["routing"])
        self.assertIn("请运营补充", data["预审_修改建议"])
        self.assertIn("批准文号/备案号/资质编号", data["预审_修改建议"])
        self.assertIn("请运营补充", data["审核_备案核查结果"])
        self.assertEqual(["FACT-PATENT-001"], [rule["rule_id"] for rule in data["matched_rules"]])
        self.assertEqual("fact", data["matched_rules"][0]["recall_channel"])
    def test_audit_endpoint_wraps_rule_engine_errors(self):
        response = audit_endpoint({"record_id": "rec_bad", "fields": {"①运营·行业领域": "美妆"}})

        self.assertEqual(-1, response["code"])
        self.assertIn("物料内容", response["msg"])


if __name__ == "__main__":
    unittest.main()
