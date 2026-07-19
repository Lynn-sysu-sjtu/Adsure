# -*- coding: utf-8 -*-
"""Tests for governed DeepSeek candidate-pool construction."""

import unittest

from candidate_governance import govern_candidates


def make_rule(uid, legacy_id, *, layer="content", source_type="平台规则", platform=None, open_rule=False, risk="高"):
    rule = {
        "rule_uid": uid,
        "rule_id": legacy_id,
        "title": uid,
        "source_type": source_type,
        "risk_level": risk,
        "recall": {
            "trigger_layer": layer,
            "catalog_recall_enabled": open_rule,
        },
    }
    if platform:
        rule["platform"] = platform
    return rule


class CandidatePoolGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.department = make_rule(
            "RUID-DEPT",
            "COSM-002",
            source_type="部门规章",
        )
        self.xhs = make_rule("RUID-XHS", "XHS-COSM-002", platform="小红书")
        self.douyin = make_rule("RUID-DY", "DY-COSM-002", platform="抖音")
        self.open_rule = make_rule(
            "RUID-OPEN",
            "GEN-GOOD-CUSTOMS-001",
            source_type="法律",
            open_rule=True,
        )
        self.groups = {
            "groups": [
                {
                    "issue_group_id": "cosmetic-filing",
                    "member_rule_uids": ["RUID-DEPT", "RUID-XHS", "RUID-DY"],
                    "selection_policy": {
                        "primary_rule_strategy": "highest_legal_authority",
                        "platform_rule_strategy": "current_platform_only",
                        "max_primary_rules": 1,
                        "max_platform_rules": 1,
                    },
                }
            ]
        }

    def test_keeps_primary_current_platform_and_open_rule(self):
        recalled = [
            (self.douyin, ["美白"]),
            (self.xhs, ["美白"]),
            (self.department, ["美白"]),
            (self.open_rule, ["llm_catalog:consumer insult"]),
        ]

        governed = govern_candidates(
            recalled,
            request={"context": {"platforms": ["小红书"]}},
            group_asset=self.groups,
            limit=8,
        )

        ids = [rule["rule_uid"] for rule, _ in governed]
        self.assertEqual(["RUID-OPEN", "RUID-DEPT", "RUID-XHS"], ids)
        self.assertNotIn("RUID-DY", ids)
        selected = {rule["rule_uid"]: rule for rule, _ in governed}
        self.assertEqual(["RUID-DY"], selected["RUID-DEPT"]["supporting_rule_uids"])

    def test_missing_platform_keeps_only_primary_group_rule(self):
        governed = govern_candidates(
            [(self.department, ["美白"]), (self.xhs, ["美白"]), (self.douyin, ["美白"])],
            request={"context": {}},
            group_asset=self.groups,
        )
        self.assertEqual(["RUID-DEPT"], [rule["rule_uid"] for rule, _ in governed])

    def test_fact_and_platform_quotas_are_enforced(self):
        recalled = []
        for index in range(6):
            recalled.append((make_rule(f"RUID-FACT-{index}", f"FACT-{index}", layer="fact", source_type="部门规章"), ["fact"] ))
        for index in range(5):
            recalled.append((make_rule(f"RUID-PLATFORM-{index}", f"PLATFORM-{index}", platform="小红书"), ["keyword"] ))

        governed = govern_candidates(
            recalled,
            request={"context": {"platforms": ["小红书"]}},
            group_asset={"groups": []},
            limit=8,
        )

        self.assertLessEqual(sum(rule["recall"]["trigger_layer"] == "fact" for rule, _ in governed), 3)
        self.assertLessEqual(sum(bool(rule.get("platform")) for rule, _ in governed), 2)
        self.assertLessEqual(len(governed), 8)

    def test_open_content_rule_reserves_a_slot_when_ranked_after_noise(self):
        noise = [
            (make_rule(f"RUID-NOISE-{index}", f"NOISE-{index}", source_type="部门规章"), ["regex:noise"])
            for index in range(10)
        ]
        governed = govern_candidates(
            noise + [(self.open_rule, ["semantic:0.81"])],
            request={"context": {}},
            group_asset={"groups": []},
            limit=8,
        )
        self.assertIn("RUID-OPEN", [rule["rule_uid"] for rule, _ in governed])

    def test_parent_scenarios_are_merged_before_governance(self):
        governed = govern_candidates(
            [(self.open_rule, ["semantic:a"]), (dict(self.open_rule), ["semantic:b"])],
            request={"context": {}},
            group_asset={"groups": []},
        )
        self.assertEqual(1, len(governed))
        self.assertEqual(["semantic:a", "semantic:b"], governed[0][1])


if __name__ == "__main__":
    unittest.main()
