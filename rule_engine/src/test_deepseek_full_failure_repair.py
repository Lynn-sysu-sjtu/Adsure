# -*- coding: utf-8 -*-
import unittest

from deepseek_full_failure_repair import repair_instruction


class FullFailureRepairTests(unittest.TestCase):
    def test_ascii_failure_instruction_requires_stable_ascii_keys(self):
        text = repair_instruction("issue keys must be stable ASCII identifiers")
        self.assertIn("ASCII", text)
        self.assertIn("category_key", text)
        self.assertIn("issue_key", text)

    def test_core_support_failure_instruction_allows_null_check(self):
        text = repair_instruction("invalid proactive_check core support")
        self.assertIn("proactive_check", text)
        self.assertIn("null", text)
        self.assertIn("逐字", text)


if __name__ == "__main__":
    unittest.main()
