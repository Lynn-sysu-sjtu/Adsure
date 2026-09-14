import json
import tempfile
import unittest
from pathlib import Path

from src import enrich_official_case_rules


class EnrichOfficialCaseRulesTests(unittest.TestCase):
    def test_enrichment_preserves_general_source_basis_and_labels_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            structured_dir = Path(tmp) / "structured"
            structured_dir.mkdir()
            case_path = structured_dir / "samr_2025_typical_ads_05.json"
            case_path.write_text(
                json.dumps(
                    {
                        "case_id": "samr_2025_typical_ads_05",
                        "legal_basis": ["《中华人民共和国广告法》有关规定"],
                        "notes": "市场监管总局公开页未公布具体条款编号。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            outputs = enrich_official_case_rules.run(
                structured_dir=structured_dir,
                rule_catalog_path=Path("data/rules/advertising_law_2021.json"),
            )
            enriched = json.loads(outputs[0].read_text(encoding="utf-8"))

        self.assertEqual(
            enriched["legal_basis"],
            ["《中华人民共和国广告法》有关规定"],
        )
        self.assertIn("ADLAW-009-03", enriched["mapped_rule_ids"])
        self.assertIn("ADLAW-057-01", enriched["possible_liability_rule_ids"])
        self.assertFalse(
            enriched["legal_basis_provenance"][
                "specific_articles_published_by_case_source"
            ]
        )
        self.assertTrue(
            all(
                detail["mapping_review_status"] == "pending_legal_review"
                for detail in enriched["legal_basis_details"]
            )
        )


if __name__ == "__main__":
    unittest.main()
