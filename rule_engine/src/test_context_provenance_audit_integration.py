import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class ContextProvenanceAuditIntegrationTests(unittest.TestCase):
    def test_audit_uses_private_context_and_keeps_public_contract(self):
        captured = {}

        def fake_judgment(context_package, matched_rules):
            captured["context"] = context_package
            return {
                "engine": "deepseek_llm_v0",
                "mode": "strict",
                "opinion_type": "违规修改",
                "overall_risk_level": "高",
                "audit_opinion": "",
                "rule_judgments": [
                    {
                        "rule_uid": item["rule_uid"],
                        "rule_id": item["rule_id"],
                        "applicability_status": "confirmed_violation",
                        "material_evidence": context_package["material_text"],
                        "satisfied_elements": ["文案直接宣称治疗癌症"],
                        "unsatisfied_elements": [],
                        "missing_facts": [],
                        "applicability_reason": "fake confirmation",
                        "confidence": 1.0,
                    }
                    for item in matched_rules
                ],
                "summary": "",
                "outside_rule_risks": [],
                "revision_suggestion": "添加本品不能代替药物声明",
                "need_legal_review": True,
                "routing": "法务",
            }

        with patch("rule_engine._judge_with_config", side_effect=fake_judgment):
            response = audit(
                {
                    "record_id": "ordinary-juice-context-conflict",
                    "mode": "标准",
                    "fields": {
                        "①运营·行业领域": "保健食品",
                        "①运营·物料内容": "治疗肝癌、肺癌、结肠癌等80%-90%癌症病类",
                        "①运营·补充背景资料": "产品为普通果汁饮品，非保健食品",
                        "①保健食品·产品品类": "果汁饮品",
                        "①保健食品·核心宣称功效": "治疗癌症",
                    },
                },
                base_dir=PROJECT_BASE,
            )

        self.assertEqual(0, response["code"])
        self.assertEqual(
            "产品为普通果汁饮品，非保健食品",
            captured["context"]["supplemental_background"],
        )
        self.assertTrue(captured["context"]["context_conflicts"])

        public_context = response["data"]["context_package"]
        self.assertNotIn("supplemental_background", public_context)
        self.assertNotIn("context_provenance", public_context)
        self.assertNotIn("context_conflicts", public_context)

        final_rules = response["data"]["matched_rules"]
        general_medical = [
            item for item in final_rules if item.get("rule_id") == "GEN-MED-001"
        ]
        self.assertTrue(general_medical)
        self.assertEqual(
            "confirmed_violation",
            general_medical[0]["applicability_status"],
        )

        for item in final_rules:
            industries = (item.get("applies_to") or {}).get("industries") or []
            if "保健食品" in industries and "通用" not in industries:
                self.assertNotEqual(
                    "confirmed_violation", item.get("applicability_status")
                )

        self.assertNotIn(
            "本品不能代替药物",
            response["data"]["预审_修改建议"],
        )


if __name__ == "__main__":
    unittest.main()
