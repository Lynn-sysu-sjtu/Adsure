# -*- coding: utf-8 -*-
import unittest

from deepseek_proactive_check_repair import proactive_check_errors, proactive_repair_instruction


class ProactiveCheckRepairTests(unittest.TestCase):
    def test_rejects_partial_model_proactive_check(self):
        errors = proactive_check_errors({"check_type": "operator_supply_docs", "description": "补材料"})
        self.assertIn("check_type", errors)
        self.assertIn("requirement", errors)

    def test_accepts_null_or_complete_check(self):
        self.assertEqual([], proactive_check_errors(None))
        complete = {"check_key": "LICENSE_CHECK", "name": "资质核验", "check_type": "qualification", "applicability": {"industries": [], "platforms": [], "material_types": []}, "trigger_conditions": {"all": [], "any": [], "exclude": []}, "requirement": "核验资质", "required_materials": ["资质文件"], "default_severity": "高"}
        self.assertEqual([], proactive_check_errors(complete))

    def test_repair_instruction_explains_null_is_preferred_to_guessing(self):
        instruction = proactive_repair_instruction()
        self.assertIn("null", instruction)
        self.assertIn("不得猜测", instruction)


if __name__ == "__main__": unittest.main()
