import json
import tempfile
import unittest
from pathlib import Path

from src import build_chunks
from src.api import CaseRepository, is_production_case


ROOT = Path(__file__).resolve().parents[1]
DEMO_CASE_IDS = {
    "mihoyo_2016_2520150399",
    "shanghai_jingan_2026_062026000257",
    "sector_docx__health__d8460228",
}


def owner_approved_candidate_ids() -> set[str]:
    """业主审批入生产（owner_approval.approved）的候选案例集合。"""
    ids: set[str] = set()
    for path in (ROOT / "data/structured_candidates").glob("*.json"):
        case = json.loads(path.read_text(encoding="utf-8"))
        oa = case.get("owner_approval") or {}
        if oa.get("approved") is True:
            ids.add(case["case_id"])
    return ids


class DemoProductionPromotionTests(unittest.TestCase):
    def test_manifest_is_explicit_and_narrow(self):
        manifest = json.loads(
            (ROOT / "data/config/demo_production_cases.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(manifest["enabled"])
        self.assertEqual(set(manifest["case_ids"]), DEMO_CASE_IDS)
        self.assertTrue(manifest["safety_boundary"]["demo_only"])
        self.assertTrue(
            manifest["safety_boundary"]["not_for_production_factual_use"]
        )

    def test_demo_cases_enter_production_without_rewriting_source_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_chunks.run(
                structured_dir=ROOT / "data/structured",
                structured_candidates_dir=ROOT / "data/structured_candidates",
                structured_samples_dir=ROOT / "data/structured_samples",
                chunks_dir=root / "chunks",
                reports_dir=root / "reports",
                demo_production_manifest=(
                    ROOT / "data/config/demo_production_cases.json"
                ),
            )
            chunks = json.loads(paths["production"].read_text(encoding="utf-8"))

        demo_chunks = [
            chunk for chunk in chunks if chunk["case_id"] in DEMO_CASE_IDS
        ]
        self.assertEqual(len(demo_chunks), 6)
        self.assertEqual({chunk["case_id"] for chunk in demo_chunks}, DEMO_CASE_IDS)
        for chunk in demo_chunks:
            metadata = chunk["metadata"]
            # d8460228、shanghai_jingan 已由业主审批入生产（非 demo），mihoyo 仍为 demo
            if chunk["case_id"] in {"sector_docx__health__d8460228", "shanghai_jingan_2026_062026000257"}:
                self.assertTrue(metadata["owner_approval"])
                self.assertFalse(metadata["demo_production"])
            else:
                self.assertTrue(metadata["demo_production"])
                self.assertTrue(metadata["demo_only"])
                self.assertTrue(metadata["not_for_production_factual_use"])
            # 硬性保证：demo/业主审批都不改写 source_verification_status 为 source_verified
            self.assertNotEqual(
                metadata["source_verification_status"],
                "source_verified",
            )

            case_path = ROOT / "data/structured" / f"{chunk['case_id']}.json"
            case = build_chunks.load_case_record(case_path)
            self.assertTrue(is_production_case(case, chunk))
            if chunk["case_id"] in {"sector_docx__health__d8460228", "shanghai_jingan_2026_062026000257"}:
                self.assertEqual(build_chunks.production_exclusion_reasons(case), [])
            else:
                self.assertTrue(case["demo_production"])
                self.assertTrue(case["demo_only"])
                self.assertTrue(build_chunks.production_exclusion_reasons(case))

    def test_three_judge_queries_hit_expected_case_first_in_production(self):
        evaluation = json.loads(
            (
                ROOT / "data/evaluation/judge_three_case_acceptance.json"
            ).read_text(encoding="utf-8")
        )
        repository = CaseRepository(ROOT / "data", "production")
        self.assertEqual(repository.load_error, "")
        self.assertEqual(
            {chunk["case_id"] for chunk in repository.chunks},
            {
                *(f"samr_2025_typical_ads_{index:02d}" for index in range(1, 11)),
                *DEMO_CASE_IDS,
                *owner_approved_candidate_ids(),
            },
        )

        for record in evaluation["records"]:
            request = record["retrieval_request"]
            results = repository.retrieve(
                request["content"],
                request["top_k"],
                request["industry"],
                requested_channels=request.get("platform") or [],
            )
            self.assertTrue(results, record["case_id"])
            first = results[0]
            self.assertEqual(
                first["case_id"],
                record["expected_first_case_id"],
                record["case_id"],
            )
            self.assertFalse(first["candidate_data"])
            self.assertTrue(first["approved_for_rag"])
            self.assertNotEqual(
                first["source_verification_status"],
                "source_verified",
            )


if __name__ == "__main__":
    unittest.main()
