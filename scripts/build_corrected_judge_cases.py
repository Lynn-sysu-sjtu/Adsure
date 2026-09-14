#!/usr/bin/env python3
"""Merge a supplied judge-case JSON with the measured RAG acceptance contract."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACCEPTANCE = ROOT / "data/evaluation/judge_three_case_acceptance.json"
DEFAULT_OUTPUT = ROOT / "参赛提交材料/adsure_judge_test_cases_3条_可验收版.json"


def build_package(source: dict[str, Any], acceptance: dict[str, Any]) -> dict[str, Any]:
    package = deepcopy(source)
    contracts = {record["case_id"]: record for record in acceptance["records"]}
    records = package.get("records") or []
    if {record.get("case_id") for record in records} != set(contracts):
        raise ValueError("source file must contain exactly JUDGE-GAME/COSM/HF-001")

    package["version"] = "1.1-acceptance-corrected"
    package["rag_mode"] = "candidate"
    package["verification_boundary"] = acceptance["acceptance_boundary"]
    package["judge_instruction"] = (
        "按原 fields 提交 /audit；类案检索必须使用每条 rag_request。"
        "RAG 首条已本地实测，/audit、飞书卡片及状态机仍须在部署环境按 expected_operations 复测。"
    )
    for record in records:
        contract = contracts[record["case_id"]]
        expected = contract["expected_output_contract"]
        record["rag_request"] = contract["retrieval_request"]
        record["expected_first_case_id"] = contract["expected_first_case_id"]
        if contract.get("retrieval_industry_note"):
            record["retrieval_industry_note"] = contract["retrieval_industry_note"]
        record["rag_acceptance"] = {
            "mode": "candidate",
            "expected_first_case_id": contract["expected_first_case_id"],
            "candidate_data": True,
            "approved_for_rag": False,
            "locally_measured": True,
        }
        record["external_workflow_acceptance"] = {
            "locally_measured": False,
            "must_be_retested_after_deployment": True,
        }
        record["human_reference"] = {
            "expected_risk_level": expected["risk_level"],
            "expected_routing": expected["routing"],
            "expected_violation_types": expected["violation_types"],
            "expected_hit_points": expected["hit_points"],
            "expected_legal_basis": "；".join(expected["legal_basis"]),
            "human_reason": expected["hit_points"],
            "notes": expected["legal_accuracy_note"],
        }
    return package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, default=DEFAULT_ACCEPTANCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    acceptance = json.loads(args.acceptance.read_text(encoding="utf-8"))
    package = build_package(source, acceptance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built corrected judge package: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
