# -*- coding: utf-8 -*-
import unittest

from legal_issue_candidate_v3_gate import validate_candidate_core_support


class CandidateV3ProactiveEnumTests(unittest.TestCase):
    def test_rejects_invalid_check_type_and_severity(self):
        rule = {
            "title": "赠送活动应明示条件",
            "legal_basis": [{"text": "赠送活动应明示参与条件。"}],
            "applies_to": {"industries": ["游戏"]},
            "rule_applicability": {},
        }
        candidate = {
            "proactive_check": {
                "name": "赠送条件核验", "check_key": "GIFT_DISCLOSURE",
                "check_type": "operator_supply_docs",
                "applicability": {"industries": ["游戏"], "platforms": [], "material_types": []},
                "trigger_conditions": {"all": [], "any": ["赠送"], "exclude": []},
                "requirement": "核验赠送活动参与条件", "required_materials": [],
                "default_severity": "严重",
                "core_support": [{"source_field": "legal_basis", "evidence": "赠送活动应明示参与条件。"}],
            }
        }
        errors = validate_candidate_core_support(candidate, rule)
        self.assertTrue(any("check_type" in item for item in errors))
        self.assertTrue(any("default_severity" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
