# -*- coding: utf-8 -*-
"""Integration test for governed candidates entering final LLM judgment."""

import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class CandidateGovernanceAuditIntegrationTests(unittest.TestCase):
    def test_audit_sends_governed_uid_candidates_to_llm(self):
        def rule(uid, legacy_id, source_type, platform=None, open_rule=False):
            item = {
                "rule_uid": uid,
                "rule_id": legacy_id,
                "title": uid,
                "risk_level": "高",
                "dimension": "测试",
                "source_type": source_type,
                "recall": {
                    "trigger_layer": "content",
                    "catalog_recall_enabled": open_rule,
                },
            }
            if platform:
                item["platform"] = platform
            return item

        department = rule("RUID-DEPT", "COSM-002", "部门规章")
        xhs = rule("RUID-XHS", "XHS-002", "平台规则", platform="小红书")
        douyin = rule("RUID-DY", "DY-002", "平台规则", platform="抖音")
        open_rule = rule("RUID-OPEN", "GEN-GOOD-CUSTOMS-001", "法律", open_rule=True)
        recalled = [
            (douyin, ["美白"]),
            (xhs, ["美白"]),
            (department, ["美白"]),
            (open_rule, ["llm_catalog:insult"]),
        ]
        groups = {
            "groups": [
                {
                    "issue_group_id": "cosmetic",
                    "member_rule_uids": ["RUID-DEPT", "RUID-XHS", "RUID-DY"],
                }
            ]
        }
        captured = {}

        def fake_judge(context_package, matched_rules):
            captured["uids"] = [item["rule_uid"] for item in matched_rules]
            return {
                "engine": "mock",
                "opinion_type": "\u8fdd\u89c4\u4fee\u6539",
                "overall_risk_level": "\u9ad8",
                "audit_opinion": "",
                "rule_judgments": [
                    {
                        "rule_uid": item["rule_uid"],
                        "rule_id": item["rule_id"],
                        "applicability_status": "confirmed_violation",
                        "material_evidence": context_package["material_text"],
                        "satisfied_elements": ["candidate applies"],
                        "unsatisfied_elements": [],
                        "missing_facts": [],
                        "applicability_reason": "test confirmation",
                        "confidence": 1.0,
                    }
                    for item in matched_rules
                ],
            }

        with (
            patch("rule_engine.recall_rules", return_value=recalled),
            patch("rule_engine.fact_recall_rules", return_value=[]),
            patch("rule_engine.load_legal_issue_groups", return_value=groups),
            patch("rule_engine._judge_with_config", side_effect=fake_judge),
        ):
            response = audit(
                {
                    "record_id": "candidate-governance",
                    "industry": "美妆",
                    "platform": ["小红书"],
                    "content": "测试文案",
                },
                base_dir=PROJECT_BASE,
            )

        self.assertEqual(0, response["code"])
        self.assertEqual(["RUID-OPEN", "RUID-DEPT", "RUID-XHS"], captured["uids"])
        self.assertEqual(3, len(response["data"]["matched_rules"]))


if __name__ == "__main__":
    unittest.main()
