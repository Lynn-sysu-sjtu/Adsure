# -*- coding: utf-8 -*-
import unittest

from deepseek_candidate_repair_strict import strict_contract_instruction


class StrictRepairPromptTests(unittest.TestCase):
    def test_instruction_locks_primary_and_terminal_enums(self):
        instruction = strict_contract_instruction()
        self.assertIn("有且仅有一个", instruction)
        for value in ("confirmed_violation", "evidence_required", "proactive_check", "no_applicable_rule"):
            self.assertIn(value, instruction)


if __name__ == "__main__": unittest.main()
