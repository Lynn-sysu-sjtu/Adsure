import json
import unittest
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]
AD_LAW_PATH = PROJECT_BASE / "jsonbase" / "20260623_中华人民共和国广告法_通用规则_v1.json"


class SemanticScenarioAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(AD_LAW_PATH.read_text(encoding="utf-8-sig"))
        cls.rules = {rule["rule_id"]: rule for rule in cls.document.get("rules", [])}

    def test_open_ended_rules_keep_parent_vector_and_add_scenarios(self):
        required_rule_ids = {
            "GEN-FALSE-001",
            "GEN-GOOD-CUSTOMS-001",
            "GEN-DISCRIMINATION-001",
            "GEN-MINOR-HEALTH-001",
            "GEN-COMPARE-001",
            "GEN-IDENT-001",
            "GEN-MED-001",
            "GEN-HEALTHSOFT-001",
            "GEN-MINOR-INDUCEMENT-001",
        }
        self.assertTrue(required_rule_ids.issubset(self.rules))
        for rule_id in required_rule_ids:
            recall = self.rules[rule_id]["recall"]
            self.assertTrue(recall.get("vector_text"), rule_id)
            self.assertTrue(recall.get("semantic_scenarios"), rule_id)
            self.assertTrue(recall.get("semantic_enabled"), rule_id)

    def test_scenario_ids_are_unique_and_vector_texts_are_short(self):
        for rule in self.rules.values():
            scenarios = (rule.get("recall") or {}).get("semantic_scenarios") or []
            scenario_ids = [scenario.get("scenario_id") for scenario in scenarios]
            self.assertEqual(len(scenario_ids), len(set(scenario_ids)), rule.get("rule_id"))
            for scenario in scenarios:
                self.assertTrue(scenario.get("scenario_id"), rule.get("rule_id"))
                self.assertTrue(scenario.get("vector_text"), rule.get("rule_id"))
                self.assertLessEqual(len(scenario["vector_text"]), 50, rule.get("rule_id"))

    def test_good_customs_rule_contains_consumer_dehumanization_scene(self):
        rule = self.rules["GEN-GOOD-CUSTOMS-001"]
        scenarios = {
            scenario["scenario_id"]: scenario["vector_text"]
            for scenario in rule["recall"]["semantic_scenarios"]
        }
        self.assertIn("consumer_dehumanization", scenarios)
        self.assertIn("狗", scenarios["consumer_dehumanization"])
        self.assertEqual("第九条第（七）项", rule["legal_basis"][0]["article"])


if __name__ == "__main__":
    unittest.main()
