import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from src.build_audit_test_cases import SELECTIONS, build_case
from src.validate_audit_cases import validate_dataset


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


if __name__ == "__main__":
    unittest.main()
