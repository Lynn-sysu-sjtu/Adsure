# -*- coding: utf-8 -*-
import unittest

from legal_issue_candidate_v3_gate import validate_candidate_core_support


class CandidateV3TopicGateTests(unittest.TestCase):
    def test_rejects_probability_topic_not_present_in_core_evidence(self):
        rule = {
            "title": "禁止虚假广告（虚构使用效果）",
            "legal_basis": [{"text": "不得虚构使用商品或者接受服务的效果。"}],
            "applies_to": {"industries": ["游戏"]},
            "rule_applicability": {"type": "明确适用型"},
        }
        candidate = {
            "proactive_check": {
                "name": "游戏实际效果核验",
                "trigger_conditions": {"all": [], "any": ["广告宣传概率或获取结果"], "exclude": []},
                "requirement": "核验游戏概率和奖池数据是否真实。",
                "required_materials": ["概率公示", "奖池数据"],
                "core_support": [{"source_field": "title", "evidence": "虚构使用效果"}],
            }
        }
        errors = validate_candidate_core_support(candidate, rule)
        self.assertTrue(any("unsupported proactive topic" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
