# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_game_semantic_ab import PHASES, load_game_cases, run_phase


PROJECT_BASE = Path(__file__).resolve().parents[1]
GAME_DATASET = PROJECT_BASE.parents[1] / "测试集" / "20260911游戏测试样例集.json"


class GameSemanticAbRunnerTests(unittest.TestCase):
    def test_loads_exactly_ten_ordered_json_cases_with_eight_scorable(self):
        cases, sources = load_game_cases(GAME_DATASET)
        self.assertEqual(
            [f"EVAL-GAME-{index:03d}" for index in range(1, 11)],
            [case["case_id"] for case in cases],
        )
        self.assertTrue(all(case["dataset"] == "游戏" for case in cases))
        self.assertTrue(all(case["source_kind"] == "json" for case in cases))
        self.assertEqual(
            8,
            sum(bool(case.get("expected", {}).get("must_recall_rule_uids")) for case in cases),
        )
        self.assertEqual("20260911游戏测试样例集.json", sources[0]["file"])

    def test_phase_configuration_is_explicit(self):
        self.assertEqual({"threshold": 0.82, "limit": 2}, PHASES["A1"])
        self.assertEqual({"threshold": 0.55, "limit": 2}, PHASES["A2"])
        self.assertEqual({"threshold": 0.55, "limit": 4}, PHASES["A3"])

    def test_run_phase_uses_uid_scoring_and_phase_named_reports(self):
        captured = {}

        def fake_runner(cases, sources, baseline_name, llm_backend, semantic_backend):
            captured.update(
                cases=cases,
                sources=sources,
                baseline_name=baseline_name,
                llm_backend=llm_backend,
                semantic_backend=semantic_backend,
                threshold=os.environ["ADSURE_FALLBACK_SEMANTIC_THRESHOLD"],
                limit=os.environ["ADSURE_FALLBACK_SEMANTIC_LIMIT"],
            )
            return {"baseline_name": baseline_name, "summary": {}, "cases": []}

        def fake_saver(report, output_dir):
            base = Path(output_dir) / report["baseline_name"]
            return base.with_suffix(".json"), Path(str(base) + "_comparison.csv")

        with tempfile.TemporaryDirectory() as directory:
            json_path, csv_path, report = run_phase(
                "A3",
                dataset_path=GAME_DATASET,
                output_dir=directory,
                runner=fake_runner,
                saver=fake_saver,
            )

        self.assertEqual("mock", captured["llm_backend"])
        self.assertEqual("zhipu", captured["semantic_backend"])
        self.assertEqual("0.55", captured["threshold"])
        self.assertEqual("4", captured["limit"])
        self.assertTrue(all(case["expected"].get("must_recall_rule_uids") is not None for case in captured["cases"]))
        self.assertIn("A3", json_path.name)
        self.assertIn("A3", csv_path.name)
        self.assertEqual("rule_uid", report["scoring_identity"])
        self.assertEqual("A3", report["phase"])

    def test_unknown_phase_is_rejected(self):
        with self.assertRaises(ValueError):
            run_phase("A9", dataset_path=GAME_DATASET, output_dir=PROJECT_BASE / "test_reports")


if __name__ == "__main__":
    unittest.main()