# -*- coding: utf-8 -*-
import json
import unittest
from pathlib import Path

from confirmed_outcome import synthesize_confirmed_outcome


BASE = Path(__file__).resolve().parents[1]
CALIBRATED_RULES = {
    "RUID-6aacf3fd76ca293f": (
        "COSM-FALSE-004",
        "20260705_中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载_规则拆解_v1.json",
    ),
    "RUID-4fb1b6a17d0a999a": (
        "COSM-CLAIM-001",
        "20260705_国家药监局关于发布《化妆品功效宣称评价规范》的公告_规则拆解_v1.json",
    ),
    "RUID-9a22a73c310fc68c": (
        "COSM-001-002",
        "20260705_国家药监局关于发布实施《化妆品标签管理办法》的公告_2022.05.01生效_20260615下载_规则拆解_v1.json",
    ),
}


class BeautyRoutingCalibrationTests(unittest.TestCase):
    def _rule(self, uid):
        rule_id, filename = CALIBRATED_RULES[uid]
        payload = json.loads(
            (BASE / "jsonbase" / "美妆" / filename).read_text(encoding="utf-8")
        )
        matches = [
            rule for rule in payload.get("rules", []) if rule.get("rule_uid") == uid
        ]
        self.assertEqual(1, len(matches), uid)
        self.assertEqual(rule_id, matches[0].get("rule_id"))
        return matches[0]

    def test_calibrated_rules_route_operator_supply_docs(self):
        for uid in CALIBRATED_RULES:
            with self.subTest(uid=uid):
                rule = self._rule(uid)
                legal = rule.get("legal_attention") or {}
                self.assertEqual("operator_supply_docs", legal.get("default_route"))
                self.assertEqual("guided_fixable", legal.get("operator_fixability"))
                self.assertEqual(
                    "operator_supply_docs",
                    (rule.get("routing") or {}).get("default_route"),
                )
                self.assertEqual("human_confirmed", legal.get("calibration_status"))

    def test_beauty_007_calibrated_rule_routes_operator(self):
        rule = dict(self._rule("RUID-6aacf3fd76ca293f"))
        rule["applicability_status"] = "confirmed_violation"

        outcome = synthesize_confirmed_outcome([rule], llm_risk="高")

        self.assertEqual("运营", outcome["routing"])
        self.assertEqual("RUID-6aacf3fd76ca293f", outcome["routing_rule_uid"])

    def test_beauty_008_calibrated_rules_route_operator(self):
        rules = []
        for uid in (
            "RUID-4fb1b6a17d0a999a",
            "RUID-6aacf3fd76ca293f",
            "RUID-9a22a73c310fc68c",
        ):
            rule = dict(self._rule(uid))
            rule["applicability_status"] = "confirmed_violation"
            rules.append(rule)

        outcome = synthesize_confirmed_outcome(rules, llm_risk="高")

        self.assertEqual("运营", outcome["routing"])
        self.assertIn(
            outcome["routing_rule_uid"],
            {
                "RUID-4fb1b6a17d0a999a",
                "RUID-6aacf3fd76ca293f",
                "RUID-9a22a73c310fc68c",
            },
        )


if __name__ == "__main__":
    unittest.main()
