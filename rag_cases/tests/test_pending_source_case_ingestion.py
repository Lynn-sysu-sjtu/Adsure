import json
import unittest
from pathlib import Path

from src.build_chunks import chunks_from_case, production_exclusion_reasons
from src.validate_cases import load_risk_dimensions, validate_case


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = ROOT / "data" / "structured_candidates"


class PendingSourceCaseIngestionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.allowed_risks = load_risk_dimensions(ROOT / "prompts" / "clean_case_prompt.md")
        cls.case_paths = [
            CANDIDATE_DIR / "mihoyo_2014_2520140214.json",
            CANDIDATE_DIR / "mihoyo_2016_2520150399.json",
            CANDIDATE_DIR / "coconut_group_2021_recruitment_ad_lead.json",
            CANDIDATE_DIR / "coconut_group_2024_coconut_juice_rubbing_ad_lead.json",
            CANDIDATE_DIR / "shanghai_jingan_2026_062026000257.json",
        ]
        cls.cases = [json.loads(path.read_text(encoding="utf-8")) for path in cls.case_paths]

    def test_candidates_validate_and_remain_outside_production(self):
        for case in self.cases:
            with self.subTest(case_id=case["case_id"]):
                errors, _issues = validate_case(case, self.allowed_risks, group="candidate")
                self.assertEqual(errors, [])
                self.assertFalse(case["approved_for_rag"])
                self.assertIsNone(case["original_decision_url"])
                self.assertEqual(case["original_decision_url_status"], "not_found")
                self.assertIn("audit_not_approved_for_rag", production_exclusion_reasons(case))
                self.assertGreaterEqual(len(chunks_from_case(case)), 1)
                raw_path = ROOT / case["raw_text_path"]
                self.assertTrue(raw_path.exists(), raw_path)

    def test_mihoyo_official_auxiliary_disclosure_preserves_exact_results(self):
        by_id = {case["case_id"]: case for case in self.cases}
        case_2014 = by_id["mihoyo_2014_2520140214"]
        case_2016 = by_id["mihoyo_2016_2520150399"]
        self.assertEqual(case_2014["case_number"], "第2520140214号")
        self.assertEqual(case_2014["illegal_income_confiscated"], 16408)
        self.assertEqual(case_2014["penalty_amount"], 20000)
        self.assertEqual(case_2016["case_number"], "第2520150399号")
        self.assertEqual(case_2016["penalty_amount"], 20000)
        for case in [case_2014, case_2016]:
            self.assertEqual(case["source_verification_status"], "official_auxiliary_evidence_only")
            self.assertIn("csrc.gov.cn", case["source_url"])
            self.assertEqual(case["mapped_rule_ids"], [])

    def test_coconut_leads_do_not_claim_unverified_penalty_facts(self):
        coconut_cases = [case for case in self.cases if case["case_id"].startswith("coconut_group_")]
        for case in coconut_cases:
            with self.subTest(case_id=case["case_id"]):
                self.assertEqual(case["source_verification_status"], "pending_official_source_lookup")
                self.assertIsNone(case["case_number"])
                self.assertIsNone(case["penalty_authority"])
                self.assertIsNone(case["penalty_amount"])
                self.assertEqual(case["source_url_role"], "official_lookup_entry_not_case_document")

    def test_civil_primogem_dispute_is_excluded_from_admin_candidates(self):
        exclusion_path = ROOT / "data" / "exclusions" / "non_admin_case_leads.json"
        exclusions = json.loads(exclusion_path.read_text(encoding="utf-8"))["items"]
        self.assertTrue(any(item["lead_id"] == "one_yuan_grab_ten_thousand_primogems" for item in exclusions))
        for path in CANDIDATE_DIR.glob("*.json"):
            case = json.loads(path.read_text(encoding="utf-8"))
            if "一万原石" in json.dumps(case, ensure_ascii=False):
                self.assertFalse(case.get("is_admin_penalty_candidate"), path)


if __name__ == "__main__":
    unittest.main()
