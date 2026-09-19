import json
import unittest
from pathlib import Path

from src.api import CaseRepository, build_query


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RetrievalQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repository = CaseRepository(PROJECT_ROOT / "data", "production")
        cls.evaluations = json.loads(
            (
                PROJECT_ROOT / "data/evaluation/retrieval_quality_cases.json"
            ).read_text(encoding="utf-8")
        )

    def retrieve(self, request: dict) -> list[dict]:
        channels = list(request.get("platform", []))
        if request.get("ad_channel"):
            channels.append(request["ad_channel"])
        return self.repository.retrieve(
            build_query(request),
            request.get("top_k", 3),
            request["industry"],
            product_category=request.get("product_category", ""),
            requested_channels=channels,
            risk_dimensions=request.get("risk_dimensions", []),
            matched_rule_ids=request.get("matched_rule_ids", []),
        )

    def test_curated_precision_regressions(self):
        failures = []
        for evaluation in self.evaluations:
            results = self.retrieve(evaluation["request"])
            case_ids = [result["case_id"] for result in results]
            if "expected_first_case_id" in evaluation:
                expected = evaluation["expected_first_case_id"]
                if not case_ids or case_ids[0] != expected:
                    failures.append(
                        f"{evaluation['evaluation_id']}: expected first {expected}, got {case_ids}"
                    )
            elif case_ids != evaluation["expected_case_ids"]:
                failures.append(
                    f"{evaluation['evaluation_id']}: expected "
                    f"{evaluation['expected_case_ids']}, got {case_ids}"
                )
        self.assertEqual(failures, [])

    def test_every_result_explains_match_and_exposes_specific_rules(self):
        for evaluation in self.evaluations:
            if "expected_first_case_id" not in evaluation:
                continue
            result = self.retrieve(evaluation["request"])[0]
            self.assertTrue(result["match_evidence"]["matched_terms"])
            self.assertGreaterEqual(
                result["match_evidence"]["query_coverage"],
                self.repository.min_query_coverage,
            )
            self.assertTrue(result["mapped_rule_ids"])
            self.assertTrue(result["legal_basis_details"])
            self.assertEqual(result["retrieval_method"], "fielded_bm25_v2")


if __name__ == "__main__":
    unittest.main()
