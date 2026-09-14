import json
import unittest
from pathlib import Path

from src.build_chunks import production_exclusion_reasons
from src.validate_cases import load_risk_dimensions, validate_case


ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = (
    ROOT
    / "data"
    / "structured_candidates"
    / "shanghai_jingan_2026_062026000257.json"
)
RAW_PATH = (
    ROOT
    / "data"
    / "raw_text"
    / "shanghai_jingan_2026_062026000257_user_supplied.json"
)
RULES_PATH = ROOT / "data" / "rules" / "advertising_law_2021.json"


class ShanghaiJinganCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = json.loads(CASE_PATH.read_text(encoding="utf-8"))
        cls.raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
        cls.rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))

    def test_exact_decision_facts_are_preserved(self):
        self.assertEqual(
            self.case["case_number"], "沪市监静处〔2026〕062026000257号"
        )
        self.assertEqual(self.case["party_name"], "上海百事得电子有限公司")
        self.assertEqual(self.case["penalty_authority"], "上海市静安区市场监督管理局")
        self.assertEqual(self.case["penalty_amount"], 200000)
        self.assertIn(
            "当我一降价，你还不是像狗一样跑过来",
            self.case["illegal_claims"],
        )
        self.assertIsNone(self.case["publish_date"])
        self.assertIsNone(self.case["decision_date"])

    def test_explicit_rules_exist_in_catalog_and_case_details(self):
        catalog_ids = {item["rule_id"] for item in self.rules["rules"]}
        self.assertTrue(
            {"ADLAW-003", "ADLAW-009-07", "ADLAW-057-01"}.issubset(catalog_ids)
        )
        self.assertEqual(
            self.case["mapped_rule_ids"], ["ADLAW-003", "ADLAW-009-07"]
        )
        self.assertEqual(self.case["liability_rule_ids"], ["ADLAW-057-01"])
        details = {
            item["rule_id"]: item for item in self.case["legal_basis_details"]
        }
        self.assertEqual(
            details["ADLAW-009-07"]["relation"],
            "explicitly_cited_applicable_rule",
        )
        self.assertEqual(
            details["ADLAW-057-01"]["relation"],
            "explicitly_cited_liability_rule",
        )

    def test_candidate_is_owner_approved_for_production_while_source_pending(self):
        self.assertTrue(self.case["approved_for_rag"])
        self.assertEqual(
            self.case["source_verification_status"],
            "pending_official_source_lookup",
        )
        self.assertIsNone(self.case["original_decision_url"])
        self.assertEqual(self.case["original_decision_url_status"], "not_found")
        self.assertEqual(production_exclusion_reasons(self.case), [])

    def test_candidate_schema_validates(self):
        allowed = load_risk_dimensions(ROOT / "prompts" / "clean_case_prompt.md")
        errors, _issues = validate_case(self.case, allowed, group="candidate")
        self.assertEqual(errors, [])

    def test_raw_text_is_traceable(self):
        self.assertEqual(
            self.case["raw_text_path"],
            "data/raw_text/shanghai_jingan_2026_062026000257_user_supplied.json",
        )
        self.assertIn(
            "沪市监静处〔2026〕062026000257号", self.raw["case_text"]
        )
        self.assertIn(
            "当我一降价，你还不是像狗一样跑过来", self.raw["case_text"]
        )


if __name__ == "__main__":
    unittest.main()
