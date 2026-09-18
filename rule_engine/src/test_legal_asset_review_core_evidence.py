# -*- coding: utf-8 -*-
import unittest

from legal_asset_review import assess_candidate_quality


class CoreEvidenceQualityTests(unittest.TestCase):
    def test_fact_check_does_not_authorize_proactive_topic(self):
        records = {"R1": {"track": "游戏", "rule": {"rule_uid": "R1", "title": "禁止虚构使用效果", "legal_basis": [{"text": "不得虚构使用效果。"}], "rule_applicability": {"type": "明确适用型"}, "fact_check": {"required_materials": ["抽卡概率", "奖池", "保底机制"]}}}}
        checks = {"checks": [{"check_id": "GAME.FALSE.PROBABILITY", "name": "抽卡概率核查", "requirement": "核验抽卡概率和保底机制", "required_materials": ["概率公示"], "basis_rule_uids": ["R1"]}]}
        warnings = assess_candidate_quality({"issues": []}, {"mappings": []}, checks, records)
        self.assertTrue(any(item["code"] == "UNSUPPORTED_PROACTIVE_TOPIC" for item in warnings))


if __name__ == "__main__": unittest.main()
