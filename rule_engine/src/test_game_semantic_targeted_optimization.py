# -*- coding: utf-8 -*-

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import rule_engine as engine
from field_mapper import map_feishu_payload
from kg_rule_store import load_rule_library
from rule_identity import rule_identity
from semantic_recall import _rule_filter_reasons


PROJECT_BASE = Path(__file__).resolve().parents[1]


EXPECTED_SCENARIOS = {
    "RUID-a3804876c20d768f": {
        "hidden_withdrawal_condition",
        "fabricated_game_income",
        "misleading_payout_access",
    },
    "RUID-922e8a32d47a9d25": {
        "unverifiable_payout_users",
        "unverifiable_income_data",
        "unsupported_user_success_claim",
    },
    "RUID-f376e1be1e207021": {
        "undisclosed_gacha_probability",
        "misleading_guaranteed_prize",
        "high_value_prize_probability_hidden",
    },
    "RUID-d8d788b3f89daab3": {
        "minor_audience_game_ad",
        "child_interest_account_targeting",
        "minor_media_recharge_promotion",
    },
    "RUID-7497913efe3a276d": {
        "parent_recharge_inducement",
        "peer_pressure_parent_purchase",
        "child_game_item_purchase",
    },
    "RUID-8c3736290884aeb7": {
        "spokesperson_unverified_daily_login",
        "spokesperson_unverified_ranking",
        "spokesperson_missing_play_records",
    },
    "RUID-7bb3f201c1db1fd8": {
        "bypass_real_name",
        "no_real_name_registration",
        "guest_mode_without_verification",
    },
    "RUID-c1efc611fdda35b0": {
        "bypass_anti_addiction",
        "unlimited_minor_playtime",
        "late_night_minor_login",
    },
}


class GameSemanticTargetedOptimizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rules = load_rule_library(PROJECT_BASE)["data"]["rules"]
        cls.rules = {rule_identity(rule): rule for rule in rules}

    def test_expected_content_rules_have_complete_short_scenarios(self):
        for uid, expected_ids in EXPECTED_SCENARIOS.items():
            recall = self.rules[uid]["recall"]
            scenarios = recall.get("semantic_scenarios") or []
            self.assertEqual(expected_ids, {item["scenario_id"] for item in scenarios}, uid)
            self.assertTrue(all(item.get("enabled") is True for item in scenarios), uid)
            self.assertTrue(all(10 <= len(item["vector_text"]) <= 50 for item in scenarios), uid)
            self.assertTrue(all(item["vector_text"][-1] in "。！？" for item in scenarios), uid)

    def test_absolute_rule_keeps_semantic_disabled_and_covers_game_phrases(self):
        rule = self.rules["RUID-b60852699e8ddd70"]
        self.assertFalse(rule["recall"]["semantic_enabled"])
        terms = set(rule["detection"]["keyword_signals"]["hit_terms"])
        self.assertTrue({"最好玩", "全球最高", "全球最大", "全球最强", "最真实"}.issubset(terms))

    def test_fact_rules_keep_fact_layer_and_expose_direct_signals(self):
        qualification = self.rules["RUID-58e192a8dddf575c"]
        self.assertEqual("fact", qualification["recall"]["trigger_layer"])
        self.assertFalse(qualification["recall"]["semantic_enabled"])
        self.assertLessEqual(len(qualification["recall"]["vector_text"]), 180)
        terms = set(qualification["detection"]["keyword_signals"]["hit_terms"])
        self.assertTrue({"无版号", "未取得版号", "无需版号", "无行政许可"}.issubset(terms))
        for uid in ("RUID-01d5d70f1845dca4", "RUID-9ecf144ad28c1c77"):
            self.assertEqual("fact", self.rules[uid]["recall"]["trigger_layer"])
            data_terms = set(self.rules[uid]["detection"]["keyword_signals"]["hit_terms"])
            self.assertTrue(
                {"好评率", "下载量", "活跃度", "统计口径", "数据出处"}.issubset(data_terms),
                uid,
            )

        real_name_terms = set(
            self.rules["RUID-7bb3f201c1db1fd8"]["detection"]["keyword_signals"]["hit_terms"]
        )
        anti_addiction_terms = set(
            self.rules["RUID-c1efc611fdda35b0"]["detection"]["keyword_signals"]["hit_terms"]
        )
        self.assertIn("注册不用实名", real_name_terms)
        self.assertTrue({"绕过防沉迷", "全时段无限制"}.issubset(anti_addiction_terms))

    def test_game_video_normalizes_to_rule_scope_value(self):
        request = map_feishu_payload(
            {
                "material": {"material_id": "game-video", "content": "游戏广告文案"},
                "context": {"industry": "游戏", "material_type": "视频"},
            }
        )
        self.assertEqual("短视频脚本中的文字内容", request["context"]["material_type"])

    def test_minor_rules_are_not_blocked_by_unavailable_context_fields(self):
        request = map_feishu_payload(
            {
                "material": {
                    "material_id": "minor-game",
                    "content": "小学生超爱玩，让爸爸妈妈帮你充值。",
                    "supplemental_background": "13岁以下受众占比超过60%",
                },
                "context": {
                    "industry": "游戏",
                    "material_type": "视频",
                    "product_category": "休闲/益智手游",
                    "scenario": "面向未成年人的下载推广",
                },
            }
        )
        for uid in ("RUID-d8d788b3f89daab3", "RUID-7497913efe3a276d"):
            reasons = _rule_filter_reasons(self.rules[uid], request, query="小学生 家长充值")
            self.assertEqual([], reasons, (uid, reasons))

    def test_keyword_and_semantic_hits_merge_for_the_same_rule_uid(self):
        rule = self.rules["RUID-c1efc611fdda35b0"]
        request = map_feishu_payload(
            {
                "material": {"material_id": "multi-channel", "content": "绕过防沉迷，全时段无限制。"},
                "context": {"industry": "游戏", "material_type": "视频"},
            }
        )
        with patch.object(
            engine,
            "semantic_recall_rules",
            return_value=[(rule, ["semantic_embedding_cached:0.575:scenario=bypass_anti_addiction"])],
        ):
            recalled = engine.recall_rules(
                [rule],
                request,
                context_package={"material_text": "绕过防沉迷，全时段无限制。"},
                fallback_supplement_threshold=0.55,
                fallback_supplement_limit=4,
            )
        self.assertEqual(1, len(recalled))
        self.assertIn("绕过防沉迷", recalled[0][1])
        self.assertTrue(any(hit.startswith("semantic_embedding_cached:") for hit in recalled[0][1]))
    def test_zhipu_fallback_defaults_and_environment_overrides(self):
        clean_env = {
            "ADSURE_SEMANTIC_BACKEND": "zhipu",
            "ADSURE_FALLBACK_SEMANTIC_THRESHOLD": "",
            "ADSURE_FALLBACK_SEMANTIC_LIMIT": "",
        }
        with patch.dict(os.environ, clean_env, clear=False):
            self.assertEqual(0.55, engine._fallback_supplement_threshold())
            self.assertTrue(hasattr(engine, "_fallback_supplement_limit"))
            self.assertEqual(4, engine._fallback_supplement_limit())
        with patch.dict(
            os.environ,
            {
                "ADSURE_FALLBACK_SEMANTIC_THRESHOLD": "0.61",
                "ADSURE_FALLBACK_SEMANTIC_LIMIT": "3",
            },
            clear=False,
        ):
            self.assertEqual(0.61, engine._fallback_supplement_threshold())
            self.assertEqual(3, engine._fallback_supplement_limit())


if __name__ == "__main__":
    unittest.main()
