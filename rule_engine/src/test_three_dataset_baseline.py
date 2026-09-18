# -*- coding: utf-8 -*-

import json
import tempfile
import unittest
from pathlib import Path

from run_three_dataset_baseline import (
    apply_uid_bindings,
    compare_json_case,
    compare_game_case,
    build_limitations,
    load_normalized_cases,
    normalize_risk_level,
    split_expected_dimensions,
)


class ThreeDatasetBaselineTest(unittest.TestCase):
    def test_load_normalized_cases_preserves_frozen_order_and_hash_source(self):
        cases = [
            {'case_id': 'HF-AD-001'},
            {'case_id': 'EVAL-GAME-001'},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frozen.json'
            path.write_text(json.dumps(cases), encoding='utf-8')
            loaded, sources = load_normalized_cases(path)
        self.assertEqual(['保健食品', '游戏'], [item['dataset'] for item in loaded])
        self.assertEqual(['json', 'json'], [item['source_kind'] for item in loaded])
        self.assertEqual(['HF-AD-001', 'EVAL-GAME-001'], [item['case_id'] for item in loaded])
        self.assertEqual('frozen_normalized_cases', sources[0]['kind'])
        self.assertEqual(64, len(sources[0]['sha256']))

    def test_load_cases_reads_all_three_json_datasets_through_one_contract(self):
        from run_three_dataset_baseline import load_cases

        dataset_dir = Path(__file__).resolve().parents[3] / '测试集'
        loaded, sources = load_cases(dataset_dir)
        self.assertEqual(30, len(loaded))
        self.assertEqual(30, len({item['case_id'] for item in loaded}))
        self.assertTrue(all(item['source_kind'] == 'json' for item in loaded))
        self.assertEqual(3, len(sources))
        game_cases = [item for item in loaded if item['case_id'].startswith('EVAL-GAME-')]
        self.assertEqual(10, len(game_cases))
        self.assertTrue(all('must_recall_rule_uids' in item['expected'] for item in game_cases))

    def test_zhipu_limitations_do_not_claim_local_semantic_backend(self):
        limitations = build_limitations('zhipu')
        self.assertFalse(any('not configured' in item or 'backend is local' in item for item in limitations))

    def test_normalize_risk_level_ignores_explanatory_suffix(self):
        self.assertEqual("高", normalize_risk_level("高风险（极高风险，涉及多项明确违法事项）"))
        self.assertEqual("中", normalize_risk_level("中风险"))

    def test_split_expected_dimensions_handles_chinese_delimiters(self):
        self.assertEqual(
            ["概率未公示", "误导性宣传"],
            split_expected_dimensions("概率未公示；误导性宣传"),
        )

    def test_compare_json_case_checks_candidate_recall_forbidden_ids_and_routing(self):
        case = {
            "expected": {
                "must_recall_rule_ids": ["A", "B"],
                "must_not_recall_rule_ids": ["X"],
                "expected_routing": "运营",
            }
        }
        comparison = compare_json_case(
            case,
            response={"code": 0, "data": {"matched_rules": [{"rule_id": "A"}], "routing": "法务"}},
            diagnostics={"candidate_rule_ids": ["A", "X"]},
        )
        self.assertEqual(["B"], comparison["missing_required_candidate_rule_ids"])
        self.assertEqual(["X"], comparison["unexpected_forbidden_candidate_rule_ids"])
        self.assertFalse(comparison["routing_match"])

    def test_compare_json_case_scores_uid_independently_from_duplicate_legacy_id(self):
        case = {
            'expected': {
                'must_recall_rule_uids': ['RUID-canonical'],
                'must_recall_rule_ids': ['GAME-AD-001'],
                'must_not_recall_rule_uids': ['RUID-forbidden'],
            }
        }
        response = {
            'code': 0,
            'data': {
                'matched_rules': [
                    {'rule_uid': 'RUID-other', 'rule_id': 'GAME-AD-001'},
                    {'rule_uid': 'RUID-forbidden', 'rule_id': 'OTHER'},
                ]
            },
        }
        diagnostics = {
            'candidate_rule_uids': ['RUID-other', 'RUID-forbidden'],
            'candidate_rule_ids': ['GAME-AD-001', 'OTHER'],
        }
        comparison = compare_json_case(case, response, diagnostics)
        self.assertTrue(comparison['required_candidate_recall_match'])
        self.assertFalse(comparison['required_candidate_uid_recall_match'])
        self.assertEqual(['RUID-canonical'], comparison['missing_required_candidate_rule_uids'])
        self.assertEqual(['RUID-forbidden'], comparison['unexpected_forbidden_candidate_rule_uids'])

    def test_compare_game_case_compares_normalized_risk_and_dimensions(self):
        case = {
            "expected": {
                "expected_risk_level": "高风险",
                "expected_dimensions": ["绝对化用语", "虚假宣传"],
            }
        }
        response = {
            "code": 0,
            "data": {
                "审核_推荐风险等级": "高",
                "审核_推荐违规类型": ["绝对化用语"],
                "matched_rules": [],
            },
        }
        comparison = compare_game_case(case, response, diagnostics={})
        self.assertTrue(comparison["risk_match"])
        self.assertEqual(["虚假宣传"], comparison["missing_expected_dimensions"])


    def test_apply_uid_bindings_overlays_corrected_uids(self):
        cases = [
            {
                "case_id": "HF-AD-001",
                "expected": {"must_recall_rule_ids": ["HF-001-001"]},
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            bindings = Path(directory) / "bindings.json"
            bindings.write_text(
                json.dumps(
                    {
                        "HF-AD-001": {
                            "must_recall": {
                                "HF-001-001": {
                                    "status": "resolved",
                                    "uid": "RUID-A",
                                    "reason": "test",
                                }
                            },
                            "must_not_recall": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
            game = Path(directory) / "game.json"
            game.write_text(json.dumps({"cases": []}), encoding="utf-8")
            applied = apply_uid_bindings(cases, bindings, game)
        self.assertEqual(1, applied)
        self.assertEqual(["RUID-A"], cases[0]["expected"]["must_recall_rule_uids"])
        self.assertEqual([], cases[0]["expected"]["must_not_recall_rule_uids"])
        self.assertEqual(
            "RUID-A",
            cases[0]["expected"]["uid_binding_status"]["HF-001-001"]["uid"],
        )

    def test_apply_uid_bindings_supports_game_mapping(self):
        cases = [{"case_id": "EVAL-GAME-001", "expected": {}}]
        with tempfile.TemporaryDirectory() as directory:
            bindings = Path(directory) / "bindings.json"
            bindings.write_text(json.dumps({}), encoding="utf-8")
            game = Path(directory) / "game.json"
            game.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "case_id": "EVAL-GAME-001",
                                "must_recall_rules": [
                                    {
                                        "rule_id": "GAME-FALSE-002",
                                        "rule_uid": "RUID-GAME",
                                        "application": "test",
                                    }
                                ],
                                "must_not_recall_rules": [],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            applied = apply_uid_bindings(cases, bindings, game)
        self.assertEqual(1, applied)
        self.assertEqual(["RUID-GAME"], cases[0]["expected"]["must_recall_rule_uids"])


if __name__ == "__main__":
    unittest.main()
