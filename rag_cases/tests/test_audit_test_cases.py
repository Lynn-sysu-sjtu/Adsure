import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from src.build_audit_test_cases import (
    BASE_BATCH_FIELDS,
    BASE_SMOKE_CASE_IDS,
    SELECTIONS,
    build_base_batch,
    build_base_cases,
    build_case,
    select_base_cases,
)
from src.validate_audit_cases import (
    validate_base_batch,
    validate_base_cases,
    validate_dataset,
)


class AuditTestCasesTest(unittest.TestCase):
    def test_selection_has_five_cases_per_industry(self):
        self.assertEqual(len(SELECTIONS), 20)
        self.assertEqual(Counter(item.industry for item in SELECTIONS), {
            "游戏": 5,
            "美妆": 5,
            "保健食品": 5,
            "通用": 5,
        })

    def test_build_case_rejects_rewritten_content(self):
        selection = SELECTIONS[0]
        source = {
            "case_id": selection.source_case_id,
            "illegal_claims": ["另一条文案"],
        }
        with self.assertRaisesRegex(ValueError, "not an exact illegal_claims value"):
            build_case(selection, source)

    def test_generated_dataset_passes_validator(self):
        repo_root = Path(__file__).resolve().parents[1]
        candidates_dir = repo_root / "data" / "structured_candidates"
        cases = []
        for selection in SELECTIONS:
            source = json.loads((candidates_dir / f"{selection.source_case_id}.json").read_text(encoding="utf-8"))
            cases.append(build_case(selection, source))

        results, dataset_errors = validate_dataset(cases, candidates_dir)
        self.assertEqual(dataset_errors, [])
        self.assertEqual([item for item in results if item[1]], [])

    def test_generated_base_v4_records_match_snapshot_fields(self):
        repo_root = Path(__file__).resolve().parents[1]
        candidates_dir = repo_root / "data" / "structured_candidates"
        schema = json.loads(
            (
                repo_root
                / "data/schemas/ads_review_base_v4_fields.json"
            ).read_text(encoding="utf-8")
        )
        canonical_cases = [
            build_case(
                selection,
                json.loads(
                    (
                        candidates_dir
                        / f"{selection.source_case_id}.json"
                    ).read_text(encoding="utf-8")
                ),
            )
            for selection in SELECTIONS
        ]
        base_cases = build_base_cases(canonical_cases, schema)
        batch = build_base_batch(base_cases)

        self.assertEqual(validate_base_cases(base_cases, schema), [])
        self.assertEqual(validate_base_batch(batch, base_cases), [])
        self.assertEqual(len(batch["fields"]), len(BASE_BATCH_FIELDS))
        self.assertEqual(len(batch["rows"]), 20)
        generic = next(
            record
            for record in base_cases["records"]
            if record["case_id"] == "REAL-GEN-001"
        )
        self.assertFalse(
            any(
                name.startswith(("①游戏·", "①美妆·", "①保健食品·"))
                for name in generic["fields"]
            )
        )
        self.assertNotIn("①运营·物料编号", batch["fields"])

        smoke_cases = select_base_cases(base_cases, BASE_SMOKE_CASE_IDS)
        smoke_batch = build_base_batch(smoke_cases)
        self.assertEqual(
            [record["case_id"] for record in smoke_cases["records"]],
            list(BASE_SMOKE_CASE_IDS),
        )
        self.assertEqual(
            validate_base_cases(smoke_cases, schema, expected_count=5),
            [],
        )
        self.assertEqual(validate_base_batch(smoke_batch, smoke_cases), [])


if __name__ == "__main__":
    unittest.main()
