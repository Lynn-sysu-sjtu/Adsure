# -*- coding: utf-8 -*-
import unittest

from rule_engine import compose_final_audit_opinion


class AuditOpinionPriorityTests(unittest.TestCase):
    def test_confirmed_risk_section_precedes_fact_verification(self):
        rules = [
            {
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "title": "广告不得违背社会良好风尚",
                "risk_level": "高",
                "dimension": "社会良好风尚",
                "applicability_status": "confirmed_violation",
                "material_evidence": "像狗一样跑过来",
                "applicability_reason": "动物化贬损消费者",
            },
            {
                "rule_id": "COSM-002",
                "title": "普通化妆品不得宣称特殊功效",
                "risk_level": "高",
                "dimension": "功效超备案",
                "applicability_status": "needs_fact_verification",
                "missing_facts": ["产品注册备案类别"],
                "applicability_reason": "需要核验备案类别",
            },
        ]

        opinion = compose_final_audit_opinion(rules, revision_suggestion="删除侮辱表达并核验备案")

        self.assertTrue(opinion.startswith("意见类型：违规修改"))
        self.assertLess(opinion.index("核心违规风险"), opinion.index("附带事实核验"))
        self.assertIn("像狗一样跑过来", opinion)
        self.assertIn("产品注册备案类别", opinion)


if __name__ == "__main__":
    unittest.main()
