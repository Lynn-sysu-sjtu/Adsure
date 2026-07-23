# -*- coding: utf-8 -*-
"""End-to-end audit tests for final-rule subsumption filtering."""

import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]
MATERIAL = "我们的美白精华一降价，你还不是像狗一样跑过来。"


def rule(uid, legacy_id, title, layer="content", route="运营"):
    return {
        "rule_uid": uid,
        "rule_id": legacy_id,
        "title": title,
        "dimension": "测试",
        "risk_level": "高",
        "source_type": "法律" if uid == "RUID-GOOD" else "部门规章",
        "recall": {"trigger_layer": layer},
        "legal_attention": {"default_route": route},
    }


class RuleSubsumptionCaseTests(unittest.TestCase):
    def test_good_customs_is_confirmed_and_cosmetic_rule_remains_fact_check(self):
        good = rule("RUID-GOOD", "GEN-GOOD-CUSTOMS-001", "广告不得违背社会良好风尚", route="法务")
        cosmetic = rule("RUID-COSM", "COSM-002", "普通化妆品不得宣称特殊功效", layer="fact")
        false = rule("RUID-FALSE", "COSM-FALSE-004", "虚构使用效果")
        minor = rule("RUID-MINOR", "IAM-MINOR-001", "未成年人媒介禁投")
        data = rule("RUID-DATA", "XHS-COSM-003", "数据引证证明材料", layer="fact")
        content_recalled = [(good, ["semantic"]), (false, ["美白"]), (minor, ["semantic"])]
        fact_recalled = [(cosmetic, ["美白"]), (data, ["数据"])]
        judgments = [
            {
                "rule_uid": "RUID-GOOD",
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "applicability_status": "confirmed_violation",
                "material_evidence": "像狗一样跑过来",
                "satisfied_elements": ["动物化贬损消费者"],
                "unsatisfied_elements": [],
                "missing_facts": [],
                "applicability_reason": "直接贬损消费者人格",
                "confidence": 0.98,
            },
            {
                "rule_uid": "RUID-COSM",
                "rule_id": "COSM-002",
                "applicability_status": "needs_fact_verification",
                "material_evidence": "美白精华",
                "satisfied_elements": ["涉及美白功效"],
                "unsatisfied_elements": ["未知备案类别"],
                "missing_facts": ["产品注册备案类别"],
                "applicability_reason": "是否违规取决于备案情况",
                "confidence": 0.9,
            },
            {
                "rule_uid": "RUID-FALSE",
                "rule_id": "COSM-FALSE-004",
                "applicability_status": "not_applicable",
                "material_evidence": "美白精华",
                "satisfied_elements": ["涉及美白"],
                "unsatisfied_elements": ["没有效果承诺"],
                "missing_facts": [],
                "applicability_reason": "产品属性不等于虚构效果",
                "confidence": 0.95,
            },
            {
                "rule_uid": "RUID-MINOR",
                "rule_id": "IAM-MINOR-001",
                "applicability_status": "not_applicable",
                "material_evidence": "",
                "satisfied_elements": [],
                "unsatisfied_elements": ["没有未成年人媒介事实"],
                "missing_facts": [],
                "applicability_reason": "不涉及未成年人媒介",
                "confidence": 0.99,
            },
            {
                "rule_uid": "RUID-DATA",
                "rule_id": "XHS-COSM-003",
                "applicability_status": "not_applicable",
                "material_evidence": "",
                "satisfied_elements": [],
                "unsatisfied_elements": ["没有数据引证"],
                "missing_facts": [],
                "applicability_reason": "文案没有数据、实验或引用",
                "confidence": 0.99,
            },
        ]

        with (
            patch("rule_engine.recall_rules", return_value=content_recalled),
            patch("rule_engine.fact_recall_rules", return_value=fact_recalled),
            patch("rule_engine.load_legal_issue_groups", return_value={"groups": []}),
            patch(
                "rule_engine._judge_with_config",
                return_value={
                    "engine": "deepseek_llm_v0",
                    "opinion_type": "违规修改",
                    "overall_risk_level": "高",
                    "audit_opinion": "意见类型：违规修改",
                    "rule_judgments": judgments,
                    "outside_rule_risks": [],
                    "revision_suggestion": "删除侮辱表达并核验备案",
                    "need_legal_review": True,
                    "routing": "法务",
                },
            ),
        ):
            response = audit(
                {"record_id": "subsumption-case", "industry": "美妆", "content": MATERIAL},
                base_dir=PROJECT_BASE,
            )

        self.assertEqual(0, response["code"])
        matched = response["data"]["matched_rules"]
        self.assertEqual(["RUID-GOOD", "RUID-COSM"], [item["rule_uid"] for item in matched])
        self.assertEqual("confirmed_violation", matched[0]["applicability_status"])
        self.assertEqual("needs_fact_verification", matched[1]["applicability_status"])
        self.assertNotIn("COSM-FALSE-004", [item["rule_id"] for item in matched])

        hit_summary = response["data"]["预审_命中要点"]
        evidence_summary = response["data"]["审核_高风险词命中"]
        self.assertIn("像狗一样跑过来", hit_summary)
        self.assertIn("产品注册备案类别", hit_summary)
        self.assertNotIn("。；", hit_summary)
        self.assertIn("像狗一样跑过来", evidence_summary)
        for value in (hit_summary, evidence_summary):
            self.assertNotIn("GEN-GOOD-CUSTOMS-001", value)
            self.assertNotIn("COSM-002", value)
            self.assertNotIn("[", value)
            self.assertNotIn("]", value)
            self.assertNotIn("regex:", value)

        self.assertIn("[GEN-GOOD-CUSTOMS-001]", response["data"]["审核_审核意见"])


if __name__ == "__main__":
    unittest.main()
