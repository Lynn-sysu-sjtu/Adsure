import unittest
from pathlib import Path
from unittest.mock import patch

from rule_engine import audit


PROJECT_BASE = Path(__file__).resolve().parents[1]


class AuditContractSemanticScenarioTests(unittest.TestCase):
    def test_good_customs_scenario_keeps_existing_audit_contract(self):
        with patch.dict(
            "os.environ",
            {
                "ADSURE_SEMANTIC_BACKEND": "local",
                "ADSURE_NO_KEYWORD_SEMANTIC_THRESHOLD": "0.01",
                "ADSURE_LLM_BACKEND": "mock",
            },
        ):
            response = audit(
                {
                    "record_id": "rec_good_customs_contract",
                    "industry": "通用",
                    "content": "我们一降价，你还不是像狗一样跑过来",
                    "mode": "标准",
                },
                base_dir=PROJECT_BASE,
            )

        self.assertEqual({"code", "msg", "data"}, set(response))
        self.assertEqual(0, response["code"])
        self.assertEqual("ok", response["msg"])
        data = response["data"]
        required_keys = {
            "resolved_mode",
            "mode_reason",
            "预审_风险等级",
            "预审_命中要点",
            "预审_修改建议",
            "审核_审核意见",
            "审核_关键实体抽取",
            "审核_高风险词命中",
            "审核_平台规则预检",
            "审核_备案核查结果",
            "审核_推荐违规类型",
            "审核_推荐风险等级",
            "matched_rules",
            "routing",
            "audit_time",
        }
        self.assertTrue(required_keys.issubset(data))
        self.assertIn(data["routing"], {"运营", "法务"})
        self.assertIsInstance(data["审核_推荐违规类型"], list)
        self.assertIsInstance(data["audit_time"], int)

        good_customs = [
            rule
            for rule in data["matched_rules"]
            if rule.get("rule_id") == "GEN-GOOD-CUSTOMS-001"
        ]
        self.assertEqual(1, len(good_customs))
        self.assertEqual("semantic", good_customs[0]["recall_channel"])


if __name__ == "__main__":
    unittest.main()
