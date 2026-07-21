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
            self.assertFalse(case["primary_decision_document_found"])
            self.assertFalse(case["approved_for_primary_penalty_rag"])
            self.assertTrue(case["approved_for_auxiliary_evidence_rag"])

    def test_coconut_leads_preserve_secondary_evidence_boundary(self):
        by_id = {case["case_id"]: case for case in self.cases}
        case_2021 = by_id["coconut_group_2021_recruitment_ad_lead"]
        case_2024 = by_id["coconut_group_2024_coconut_juice_rubbing_ad_lead"]

        self.assertEqual(case_2021["reported_decision_number"], "琼市监处19号")
        self.assertIsNone(case_2021["decision_number_normalized"])
        self.assertEqual(case_2021["source_verification_status"], "credible_secondary_source_verified")
        self.assertEqual(case_2021["penalty_amount"], 400000)

        self.assertEqual(case_2024["source_verification_status"], "credible_secondary_source_only")
        self.assertEqual(case_2024["party_name"], "椰树集团有限公司")
        self.assertEqual(case_2024["penalty_amount"], 400000)
        self.assertIn("用椰子擦乳", case_2024["illegal_claims"])
        self.assertIn("用椰汁擦乳", case_2024["illegal_claims"])

        for case in [case_2021, case_2024]:
            with self.subTest(case_id=case["case_id"]):
                self.assertIsNone(case["case_number"])
                self.assertIsNone(case["original_decision_url"])
                self.assertEqual(case["source_url_role"], "credible_secondary_report_not_case_document")
                self.assertFalse(case["approved_for_rag"])

    def test_civil_primogem_dispute_is_excluded_from_admin_candidates(self):
        exclusion_path = ROOT / "data" / "exclusions" / "non_admin_case_leads.json"
        exclusions = json.loads(exclusion_path.read_text(encoding="utf-8"))["items"]
        exclusion = next(item for item in exclusions if item["lead_id"] == "one_yuan_grab_ten_thousand_primogems")
        self.assertFalse(exclusion["administrative_penalty"])
        self.assertTrue(exclusion["approved_for_civil_case_auxiliary_rag"])
        auxiliary_path = ROOT / exclusion["auxiliary_record_path"]
        auxiliary = json.loads(auxiliary_path.read_text(encoding="utf-8"))
        self.assertTrue(auxiliary["exclude_from_administrative_penalty_corpus"])
        self.assertFalse(auxiliary["indexed_in_candidate_chunks"])
        self.assertFalse(auxiliary["indexed_in_production_chunks"])
        for path in CANDIDATE_DIR.glob("*.json"):
            case = json.loads(path.read_text(encoding="utf-8"))
            if "一万原石" in json.dumps(case, ensure_ascii=False):
                self.assertFalse(case.get("is_admin_penalty_candidate"), path)


if __name__ == "__main__":
    unittest.main()
