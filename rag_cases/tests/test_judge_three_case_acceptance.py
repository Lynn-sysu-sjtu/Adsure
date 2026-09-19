import json
import unittest
from pathlib import Path

from src.validate_judge_acceptance import execute_acceptance, validate_contract


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE_PATH = PROJECT_ROOT / "data/evaluation/judge_three_case_acceptance.json"


class JudgeThreeCaseAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = json.loads(ACCEPTANCE_PATH.read_text(encoding="utf-8"))

    def test_output_contract_is_legally_normalized(self):
        self.assertEqual(validate_contract(self.payload["records"]), [])

    def test_candidate_rag_returns_expected_first_hit_for_all_three(self):
        report = execute_acceptance(self.payload)
        self.assertTrue(report["overall_local_acceptance_passed"], report)
        self.assertEqual(report["rag_acceptance"]["passed_count"], 3)
        self.assertFalse(report["external_audit_and_feishu"]["executed"])


if __name__ == "__main__":
    unittest.main()
