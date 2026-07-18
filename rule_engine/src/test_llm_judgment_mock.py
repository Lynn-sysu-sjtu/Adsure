import unittest
from pathlib import Path

from llm_judgment import judge_with_mock_llm
from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class LlmJudgmentMockTests(unittest.TestCase):
    def test_mock_llm_returns_rule_judgments_and_audit_opinion(self):
        result = judge_with_mock_llm(
            context_package={
                "material_text": "15天见效，全网第一",
                "industry": "美妆",
                "core_claims": ["改善肤色"],
            },
            matched_rules=[
                {
                    "rule_id": "GEN-FALSE-001",
                    "title": "广告不得作虚假或引人误解宣传",
                    "dimension": "虚假宣传",
                    "risk_level": "高",
                    "match_reason": "命中召回信号：15天、全网第一",
                    "legal_basis": ["AL第二十八条"],
                }
            ],
        )

        self.assertEqual("高", result["overall_risk_level"])
        self.assertEqual("mock_llm_v0", result["engine"])
        self.assertEqual("GEN-FALSE-001", result["rule_judgments"][0]["rule_id"])
        self.assertIn("疑似违规", result["rule_judgments"][0]["judgment"])
        self.assertIn("广告不得作虚假或引人误解宣传", result["audit_opinion"])
        self.assertIn("①风险定性", result["audit_opinion"])
        self.assertIn("⑥风险定级", result["audit_opinion"])

    def test_rule_engine_uses_mock_llm_judgment(self):
        response = audit(
            {
                "record_id": "rec_llm_mock",
                "mode": "标准",
                "fields": {
                    "①运营·行业领域": "美妆",
                    "①运营·物料内容": "15天见效，全网第一，焕发新生",
                    "①美妆·物料类型": "Banner",
                    "①美妆·投放平台": ["抖音"],
                    "①美妆·产品品类": "护肤",
                    "①美妆·核心宣称功效": "改善肤色",
                },
            },
            base_dir=PROJECT_BASE,
        )

        self.assertEqual(0, response["code"])
        data = response["data"]
        self.assertEqual("mock_llm_v0", data["llm_judgment"]["engine"])
        self.assertGreaterEqual(len(data["llm_judgment"]["rule_judgments"]), 1)
        self.assertIn("rule_judgments", data)


if __name__ == "__main__":
    unittest.main()
