import json
import unittest
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]
GAME_AD_LAW_PATH = next(
    path
    for path in (PROJECT_BASE / "jsonbase" / "游戏").glob("*中华人民共和国广告法*规则拆解_v1.json")
)
CASE_PATH = PROJECT_BASE / "test_cases" / "rule_engine_cases_v0.1.json"


class GameProbabilityRuleAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = json.loads(GAME_AD_LAW_PATH.read_text(encoding="utf-8-sig"))
        cls.rule = next(
            rule for rule in document["rules"] if rule["rule_id"] == "GAME-FALSE-004"
        )

    def test_game_false_rule_contains_probability_scenarios(self):
        scenarios = {
            item["scenario_id"]: item
            for item in self.rule["recall"]["semantic_scenarios"]
        }
        expected = {
            "loot_rate_exaggeration",
            "guaranteed_reward_claim",
            "probability_conditions_omitted",
            "loot_pool_mismatch",
            "guarantee_conditions_hidden",
        }
        self.assertEqual(expected, set(scenarios))
        self.assertTrue(all(item.get("enabled") is True for item in scenarios.values()))
        self.assertTrue(
            all(len(item["vector_text"]) <= 50 for item in scenarios.values())
        )

    def test_game_false_rule_preserves_identity_and_legal_boundary(self):
        self.assertEqual("RUID-fcb662545294a3a6", self.rule["rule_uid"])
        self.assertEqual("fallback", self.rule["recall"]["semantic_role"])
        decision = self.rule["detection"]["decision"]
        self.assertIn("needs_fact_verification", decision)
        self.assertIn("confirmed_violation", decision)
        self.assertNotIn("广告法规定概率公示义务", decision)

    def test_game_false_rule_requests_probability_mechanism_materials(self):
        materials = set(self.rule["fact_check"]["required_materials"])
        self.assertTrue(
            {
                "游戏内或官网概率公示页",
                "实际奖池配置",
                "各等级道具掉落概率",
                "保底机制",
                "活动期限和适用对象",
            }.issubset(materials)
        )

    def test_game_probability_case_is_in_permanent_baseline(self):
        cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))
        case = next(
            item for item in cases if item["case_id"] == "CASE-GAME-PROB-001"
        )
        self.assertEqual(
            ["GAME-FALSE-004"], case["expected"]["must_recall_rule_ids"]
        )
        self.assertEqual(
            ["GAME-FALSE-004"],
            case["expected"]["expected_fact_verification_rule_ids"],
        )
        self.assertEqual([], case["expected"]["expected_confirmed_rule_ids"])


if __name__ == "__main__":
    unittest.main()
