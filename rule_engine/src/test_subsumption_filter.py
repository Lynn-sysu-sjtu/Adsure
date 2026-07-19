# -*- coding: utf-8 -*-
"""Tests for strict validation and filtering of LLM subsumption output."""

import copy
import unittest

from subsumption import SubsumptionValidationError, validate_subsumption_result


class SubsumptionFilterTests(unittest.TestCase):
    def setUp(self):
        self.material = "我们的美白精华一降价，你还不是像狗一样跑过来。"
        self.candidates = [
            {
                "rule_uid": "RUID-GOOD",
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "title": "广告不得违背社会良好风尚",
                "dimension": "社会良好风尚",
                "risk_level": "高",
            },
            {
                "rule_uid": "RUID-COSM",
                "rule_id": "COSM-002",
                "title": "普通化妆品不得宣称特殊功效",
                "dimension": "功效超备案",
                "risk_level": "高",
            },
            {
                "rule_uid": "RUID-FALSE",
                "rule_id": "COSM-FALSE-004",
                "title": "虚构使用效果",
                "dimension": "虚假宣传",
                "risk_level": "高",
            },
        ]
        self.judgments = [
            {
                "rule_uid": "RUID-GOOD",
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "applicability_status": "confirmed_violation",
                "material_evidence": "像狗一样跑过来",
                "satisfied_elements": ["动物化贬损消费者"],
                "unsatisfied_elements": [],
                "missing_facts": [],
                "applicability_reason": "文案直接贬损消费者人格",
                "confidence": 0.96,
            },
            {
                "rule_uid": "RUID-COSM",
                "rule_id": "COSM-002",
                "applicability_status": "needs_fact_verification",
                "material_evidence": "美白精华",
                "satisfied_elements": ["涉及美白功效"],
                "unsatisfied_elements": ["尚不清楚产品备案类别"],
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
                "unsatisfied_elements": ["没有具体效果承诺或虚构事实"],
                "missing_facts": [],
                "applicability_reason": "产品功效类别描述不等于虚假效果",
                "confidence": 0.95,
            },
        ]

    def test_keeps_confirmed_and_fact_verification_but_filters_not_applicable(self):
        result = validate_subsumption_result(self.candidates, self.judgments, self.material)

        self.assertEqual(["RUID-GOOD", "RUID-COSM"], [rule["rule_uid"] for rule in result.final_rules])
        self.assertEqual(["RUID-FALSE"], [rule["rule_uid"] for rule in result.rejected_rules])
        self.assertEqual("确认适用", result.final_rules[0]["judgment"])
        self.assertEqual("需事实核验", result.final_rules[1]["judgment"])

    def test_requires_every_candidate_exactly_once(self):
        with self.assertRaisesRegex(SubsumptionValidationError, "exactly once"):
            validate_subsumption_result(self.candidates, self.judgments[:-1], self.material)

        duplicated = self.judgments + [copy.deepcopy(self.judgments[0])]
        with self.assertRaisesRegex(SubsumptionValidationError, "exactly once"):
            validate_subsumption_result(self.candidates, duplicated, self.material)

    def test_rejects_uid_outside_candidate_pool(self):
        judgments = copy.deepcopy(self.judgments)
        judgments[-1]["rule_uid"] = "RUID-OUTSIDE"
        with self.assertRaisesRegex(SubsumptionValidationError, "exactly once"):
            validate_subsumption_result(self.candidates, judgments, self.material)

    def test_confirmed_violation_requires_continuous_original_evidence(self):
        judgments = copy.deepcopy(self.judgments)
        judgments[0]["material_evidence"] = "消费者受到动物化贬损"
        with self.assertRaisesRegex(SubsumptionValidationError, "evidence"):
            validate_subsumption_result(self.candidates, judgments, self.material)

    def test_evidence_matching_normalizes_full_width_characters(self):
        material = "限时ＡＢＣ优惠"
        candidates = [self.candidates[0]]
        judgment = copy.deepcopy(self.judgments[0])
        judgment["material_evidence"] = "ABC优惠"

        result = validate_subsumption_result(candidates, [judgment], material)

        self.assertEqual(1, len(result.final_rules))

    def test_fact_verification_requires_missing_facts(self):
        judgments = copy.deepcopy(self.judgments)
        judgments[1]["missing_facts"] = []
        with self.assertRaisesRegex(SubsumptionValidationError, "missing_facts"):
            validate_subsumption_result(self.candidates, judgments, self.material)

    def test_rejects_illegal_status_and_wrong_field_types(self):
        judgments = copy.deepcopy(self.judgments)
        judgments[0]["applicability_status"] = "maybe"
        with self.assertRaisesRegex(SubsumptionValidationError, "status"):
            validate_subsumption_result(self.candidates, judgments, self.material)

        judgments = copy.deepcopy(self.judgments)
        judgments[0]["satisfied_elements"] = "not-a-list"
        with self.assertRaisesRegex(SubsumptionValidationError, "satisfied_elements"):
            validate_subsumption_result(self.candidates, judgments, self.material)

    def test_does_not_mutate_candidates_or_judgments(self):
        candidates_before = copy.deepcopy(self.candidates)
        judgments_before = copy.deepcopy(self.judgments)

        validate_subsumption_result(self.candidates, self.judgments, self.material)

        self.assertEqual(candidates_before, self.candidates)
        self.assertEqual(judgments_before, self.judgments)


if __name__ == "__main__":
    unittest.main()
