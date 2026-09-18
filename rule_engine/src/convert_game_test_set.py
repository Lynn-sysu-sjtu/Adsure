# -*- coding: utf-8 -*-
"""Convert the reviewed game XLSX test set into the shared JSON contract."""

import argparse
import hashlib
import json
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = PROJECT_BASE.parents[1]
DEFAULT_XLSX_PATH = WORKSPACE_BASE / "测试集" / "20260911游戏测试样例集.xlsx"
DEFAULT_MAPPING_PATH = PROJECT_BASE / "assets" / "game_test_expected_rule_mapping_20260917.json"
DEFAULT_OUTPUT_PATH = WORKSPACE_BASE / "测试集" / "20260911游戏测试样例集.json"
DEFAULT_EVIDENCE_PATH = PROJECT_BASE / "reports" / "game_test_json_conversion_20260917" / "conversion_evidence.json"
DEFAULT_JSONBASE_DIR = PROJECT_BASE / "jsonbase"

CASE_ID_COLUMN = "评测编号"
INPUT_COLUMNS = [
    "①运营·物料内容",
    "①游戏·投放平台",
    "①游戏·产品品类",
    "①游戏·游戏名称",
    "①游戏·物料类型",
    "①游戏·物料涉及场景",
    "①游戏·IP名称",
    "①运营·补充背景资料",
]
ANSWER_COLUMNS = [
    "标准答案·风险等级",
    "标准答案·核心违规判定",
    "标准答案·违规类型",
    "标准答案·高风险词",
    "标准答案·预期引用法条",
    "标准答案·修改建议",
    "备注·违规性质",
]


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_rule_records(value):
    if isinstance(value, dict):
        if value.get("rule_uid"):
            yield value
        for child in value.values():
            yield from _walk_rule_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_rule_records(child)


def _rules_by_uid(jsonbase_dir):
    result = {}
    for path in Path(jsonbase_dir).rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for rule in _walk_rule_records(document):
            result.setdefault(rule["rule_uid"], []).append(rule)
    return result


def read_game_rows(xlsx_path):
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to convert the game XLSX") from exc

    workbook = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.values)
    if not rows:
        raise ValueError("game XLSX is empty")
    headers = list(rows[0])
    expected_headers = [CASE_ID_COLUMN, *INPUT_COLUMNS, *ANSWER_COLUMNS]
    if headers != expected_headers:
        raise ValueError(f"unexpected game XLSX headers: {headers!r}")
    result = [dict(zip(headers, row)) for row in rows[1:] if any(value is not None for value in row)]
    if len(result) != 10:
        raise ValueError(f"expected 10 game rows, found {len(result)}")
    return result


def load_expectation_mapping(path):
    document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cases = document.get("cases") or []
    case_ids = [case.get("case_id") for case in cases]
    expected_ids = [f"EVAL-GAME-{index:03d}" for index in range(1, 11)]
    if case_ids != expected_ids:
        raise ValueError(f"unexpected expectation case order: {case_ids}")
    return document


def build_game_test_set(rows, expectations, jsonbase_dir):
    mapping_by_case = {item["case_id"]: item for item in expectations["cases"]}
    rules_by_uid = _rules_by_uid(jsonbase_dir)
    cases = []
    for row in rows:
        case_id = row[CASE_ID_COLUMN]
        expectation = mapping_by_case.get(case_id)
        if expectation is None:
            raise ValueError(f"missing expectation mapping for {case_id}")
        required_rules = expectation.get("must_recall_rules") or []
        forbidden_rules = expectation.get("must_not_recall_rules") or []
        for declared in [*required_rules, *forbidden_rules]:
            matches = rules_by_uid.get(declared["rule_uid"], [])
            if len(matches) != 1:
                raise ValueError(f"UID must resolve exactly once: {declared['rule_uid']}")
            if matches[0].get("rule_id") != declared["rule_id"]:
                raise ValueError(f"UID/ID mismatch: {declared}")

        input_fields = {column: row.get(column) for column in INPUT_COLUMNS}
        input_fields.update({
            "①运营·行业领域": "游戏",
            "①运营·紧急程度": "普通",
            "①运营·投放平台": [row.get("①游戏·投放平台")],
        })
        source_answer = {column: row.get(column) for column in ANSWER_COLUMNS}
        cases.append({
            "case_id": case_id,
            "name": row.get("标准答案·核心违规判定") or case_id,
            "label": row.get("标准答案·违规类型"),
            "test_focus": row.get("标准答案·核心违规判定"),
            "input_payload": {
                "record_id": "rec_" + case_id.lower().replace("-", "_"),
                "mode": "标准",
                "fields": input_fields,
            },
            "expected": {
                "expected_judgment": row.get("标准答案·核心违规判定"),
                "expected_risk_level": row.get("标准答案·风险等级"),
                "expected_dimensions": row.get("标准答案·违规类型"),
                "expected_routing": None,
                "must_recall_rule_uids": [item["rule_uid"] for item in required_rules],
                "must_recall_rule_ids": [item["rule_id"] for item in required_rules],
                "must_not_recall_rule_uids": [item["rule_uid"] for item in forbidden_rules],
                "must_not_recall_rule_ids": [item["rule_id"] for item in forbidden_rules],
                "expected_rule_details": required_rules,
                "forbidden_rule_details": forbidden_rules,
                "unmapped_expected_provisions": expectation.get("unmapped_expected_provisions") or [],
                "source_answer": source_answer,
            },
        })

    return {
        "test_set_id": "game-ad-compliance-rule-recall-20260911",
        "name": "游戏广告合规测试样例集",
        "version": "2026-09-17.uid-recall-v1",
        "purpose": "统一评测规则引擎实际规则召回与人工审核预期规则清单的差异。",
        "input_contract": {
            "source_format": "xlsx",
            "source_sheet": "游戏广告合规评测案例集",
            "source_input_columns": INPUT_COLUMNS,
            "platform_normalization": "①运营·投放平台保存为单元素数组，同时保留①游戏·投放平台原值。",
        },
        "reference_answer_contract": {
            "primary_identity": "must_recall_rule_uids",
            "compatibility_identity": "must_recall_rule_ids",
            "unmapped_policy": "找不到直接对应的有效 JSONBase 规则时记录在 unmapped_expected_provisions，不虚构 UID。",
            "source_answer_columns": ANSWER_COLUMNS,
        },
        "cases": cases,
    }


def write_game_test_set(document, output_path, evidence_path, source_xlsx_path, mapping_path):
    output_path = Path(output_path)
    evidence_path = Path(evidence_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence = {
        "source_xlsx_path": str(Path(source_xlsx_path).resolve()),
        "source_xlsx_sha256": _sha256(source_xlsx_path),
        "mapping_path": str(Path(mapping_path).resolve()),
        "mapping_sha256": _sha256(mapping_path),
        "output_path": str(output_path.resolve()),
        "output_sha256": _sha256(output_path),
        "row_count": len(document["cases"]),
        "case_ids": [case["case_id"] for case in document["cases"]],
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX_PATH))
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING_PATH))
    parser.add_argument("--jsonbase", default=str(DEFAULT_JSONBASE_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE_PATH))
    args = parser.parse_args()

    rows = read_game_rows(args.xlsx)
    expectations = load_expectation_mapping(args.mapping)
    document = build_game_test_set(rows, expectations, args.jsonbase)
    evidence = write_game_test_set(document, args.output, args.evidence, args.xlsx, args.mapping)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
