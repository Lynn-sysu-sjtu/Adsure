import json
import unittest
from pathlib import Path

from scripts.build_corrected_judge_cases import build_package


ROOT = Path(__file__).resolve().parents[1]


class CorrectedJudgePackageTests(unittest.TestCase):
    def test_generated_package_matches_acceptance_contract(self):
        source = json.loads(
            (ROOT / "参赛提交材料/adsure_judge_test_cases_3条_可验收版.json").read_text(
                encoding="utf-8"
            )
        )
        acceptance = json.loads(
            (ROOT / "data/evaluation/judge_three_case_acceptance.json").read_text(
                encoding="utf-8"
            )
        )
        rebuilt = build_package(source, acceptance)
        records = {record["case_id"]: record for record in rebuilt["records"]}
        self.assertEqual(len(records), 3)
        self.assertEqual(
            records["JUDGE-COSM-001"]["expected_first_case_id"],
            "shanghai_jingan_2026_062026000257",
        )
        self.assertNotIn(
            "第九条第七款",
            records["JUDGE-COSM-001"]["human_reference"]["expected_legal_basis"],
        )
        self.assertNotIn(
            "网络游戏管理暂行办法",
            records["JUDGE-GAME-001"]["human_reference"]["expected_legal_basis"],
        )


if __name__ == "__main__":
    unittest.main()
