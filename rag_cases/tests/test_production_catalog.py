import json
import tempfile
import unittest
from pathlib import Path

from src import build_chunks, validate_cases


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRUCTURED_DIR = PROJECT_ROOT / "data/structured"
RAW_TEXT_PATH = PROJECT_ROOT / "data/raw_text/samr_typical_ads__2ad160ae3056.json"
EXPECTED_CASE_IDS = {
    f"samr_2025_typical_ads_{index:02d}"
    for index in range(1, 11)
}


class ProductionCatalogTests(unittest.TestCase):
    def test_all_ten_official_cases_are_traceable_and_formally_complete(self):
        raw_text = json.loads(RAW_TEXT_PATH.read_text(encoding="utf-8"))["case_text"]
        paths = sorted(STRUCTURED_DIR.glob("samr_2025_typical_ads_*.json"))
        cases = [json.loads(path.read_text(encoding="utf-8")) for path in paths]

        self.assertEqual({case["case_id"] for case in cases}, EXPECTED_CASE_IDS)
        allowed_risks = validate_cases.load_risk_dimensions()
        for case in cases:
            errors, _issues = validate_cases.validate_case(
                case,
                allowed_risks,
                "production",
            )
            self.assertEqual(errors, [], case["case_id"])
            self.assertEqual(
                build_chunks.production_exclusion_reasons(case),
                [],
                case["case_id"],
            )
            self.assertIn(case["title"], raw_text)
            self.assertIn(case["penalty_result"], raw_text)
            self.assertEqual(
                case["legal_basis"],
                ["《中华人民共和国广告法》有关规定"],
            )
            self.assertEqual(case["mapped_rule_ids"], [])
            self.assertIn("未公布具体条款编号", case["notes"])

    def test_official_catalog_builds_twenty_production_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_chunks.run(
                structured_dir=STRUCTURED_DIR,
                structured_candidates_dir=PROJECT_ROOT / "data/structured_candidates",
                structured_samples_dir=PROJECT_ROOT / "data/structured_samples",
                chunks_dir=root / "chunks",
                reports_dir=root / "reports",
            )
            chunks = json.loads(paths["production"].read_text(encoding="utf-8"))

        self.assertEqual(len(chunks), 20)
        self.assertEqual({chunk["case_id"] for chunk in chunks}, EXPECTED_CASE_IDS)
        self.assertTrue(
            all(chunk["metadata"]["violation_type"] for chunk in chunks)
        )


if __name__ == "__main__":
    unittest.main()
