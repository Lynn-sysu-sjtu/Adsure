# -*- coding: utf-8 -*-

import json
import tempfile
import unittest
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = PROJECT_BASE.parents[1]
MAPPING_PATH = PROJECT_BASE / "assets" / "game_test_expected_rule_mapping_20260917.json"
XLSX_PATH = WORKSPACE_BASE / "测试集" / "20260911游戏测试样例集.xlsx"
OUTPUT_PATH = WORKSPACE_BASE / "测试集" / "20260911游戏测试样例集.json"
JSONBASE_DIR = PROJECT_BASE / "jsonbase"


def _walk_rule_records(value):
    if isinstance(value, dict):
        if value.get("rule_uid"):
            yield value
        for child in value.values():
            yield from _walk_rule_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_rule_records(child)


def _rules_by_uid():
    rules = {}
    for path in JSONBASE_DIR.rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for rule in _walk_rule_records(document):
            rules.setdefault(rule["rule_uid"], []).append(rule)
    return rules


class GameExpectationContractTests(unittest.TestCase):
    def test_curated_mapping_resolves_every_declared_uid(self):
        self.assertTrue(MAPPING_PATH.exists(), f"missing curated mapping: {MAPPING_PATH}")
        mapping = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
        cases = mapping["cases"]
        self.assertEqual(
            [f"EVAL-GAME-{index:03d}" for index in range(1, 11)],
            [case["case_id"] for case in cases],
        )
        rules_by_uid = _rules_by_uid()
        for case in cases:
            declared = case.get("must_recall_rules") or []
            unmapped = case.get("unmapped_expected_provisions") or []
            self.assertTrue(declared or unmapped, case["case_id"])
            uids = [item["rule_uid"] for item in declared]
            self.assertEqual(len(uids), len(set(uids)), case["case_id"])
            for item in declared:
                matches = rules_by_uid.get(item["rule_uid"], [])
                self.assertEqual(1, len(matches), item)
                self.assertEqual(item["rule_id"], matches[0].get("rule_id"), item)
                self.assertEqual("direct", item.get("expectation_role"), item)


class GameTestConversionTests(unittest.TestCase):
    def test_converter_preserves_source_and_exposes_uid_contract(self):
        from convert_game_test_set import (
            build_game_test_set,
            load_expectation_mapping,
            read_game_rows,
            write_game_test_set,
        )

        rows = read_game_rows(XLSX_PATH)
        expectations = load_expectation_mapping(MAPPING_PATH)
        document = build_game_test_set(rows, expectations, JSONBASE_DIR)
        self.assertEqual(10, len(document["cases"]))
        self.assertEqual(
            [f"EVAL-GAME-{index:03d}" for index in range(1, 11)],
            [case["case_id"] for case in document["cases"]],
        )
        required_wrapper_keys = {
            "test_set_id", "name", "version", "purpose", "input_contract",
            "reference_answer_contract", "cases",
        }
        self.assertTrue(required_wrapper_keys.issubset(document))
        for source_row, case in zip(rows, document["cases"]):
            self.assertEqual(source_row, case["expected"]["source_answer"] | {
                key: case["input_payload"]["fields"].get(key)
                for key in document["input_contract"]["source_input_columns"]
            } | {"评测编号": case["case_id"]})
            expected = case["expected"]
            self.assertEqual(len(expected["must_recall_rule_uids"]), len(expected["must_recall_rule_ids"]))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "game.json"
            evidence = Path(directory) / "evidence.json"
            write_game_test_set(document, output, evidence, XLSX_PATH, MAPPING_PATH)
            first = output.read_bytes()
            write_game_test_set(document, output, evidence, XLSX_PATH, MAPPING_PATH)
            self.assertEqual(first, output.read_bytes())
            proof = json.loads(evidence.read_text(encoding="utf-8"))
            self.assertEqual(10, proof["row_count"])
            self.assertEqual(64, len(proof["source_xlsx_sha256"]))
            self.assertEqual(64, len(proof["mapping_sha256"]))
            self.assertEqual(64, len(proof["output_sha256"]))


if __name__ == "__main__":
    unittest.main()
