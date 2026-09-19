#!/usr/bin/env python3
"""Execute the three judge RAG requests and validate their output contract."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from src.api import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data/evaluation/judge_three_case_acceptance.json"
DEFAULT_REPORT = PROJECT_ROOT / "data/reports/judge_three_case_acceptance_report.json"


def validate_contract(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    by_id = {record.get("case_id"): record for record in records}
    if set(by_id) != {"JUDGE-GAME-001", "JUDGE-COSM-001", "JUDGE-HF-001"}:
        errors.append("case_ids_must_be_exactly_the_three_judge_samples")

    for case_id, record in by_id.items():
        expected = record.get("expected_output_contract") or {}
        if expected.get("risk_level") != "高":
            errors.append(f"{case_id}:risk_level_must_be_high")
        if expected.get("routing") != "法务":
            errors.append(f"{case_id}:routing_must_be_legal")
        for field in ("violation_types", "legal_basis"):
            value = expected.get(field)
            if not isinstance(value, list) or not value:
                errors.append(f"{case_id}:{field}_must_be_nonempty")
        if not str(expected.get("hit_points") or "").strip():
            errors.append(f"{case_id}:hit_points_missing")

    game_basis = " ".join(
        by_id.get("JUDGE-GAME-001", {})
        .get("expected_output_contract", {})
        .get("legal_basis", [])
    )
    if "网络游戏管理暂行办法" in game_basis:
        errors.append("JUDGE-GAME-001:obsolete_interim_measures_must_not_be_legal_basis")
    if "文市发〔2016〕32号" not in game_basis:
        errors.append("JUDGE-GAME-001:probability_disclosure_source_missing")

    beauty_basis = " ".join(
        by_id.get("JUDGE-COSM-001", {})
        .get("expected_output_contract", {})
        .get("legal_basis", [])
    )
    if "第九条第七款" in beauty_basis or "第九条第（七）项" not in beauty_basis:
        errors.append("JUDGE-COSM-001:article_9_item_7_citation_incorrect")

    health_basis = " ".join(
        by_id.get("JUDGE-HF-001", {})
        .get("expected_output_contract", {})
        .get("legal_basis", [])
    )
    if "第十七条" not in health_basis:
        errors.append("JUDGE-HF-001:advertising_law_article_17_missing")
    return errors


def execute_acceptance(
    payload: dict[str, Any],
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    records = payload.get("records") or []
    contract_errors = validate_contract(records)
    client = TestClient(
        create_app(
            data_dir=data_dir or PROJECT_ROOT / "data",
            index_scope="candidate",
            api_key="judge-acceptance-local",
        )
    )
    health = client.get("/health").json()
    observed: list[dict[str, Any]] = []
    for record in records:
        response = client.post(
            "/cases/retrieve",
            headers={"X-API-Key": "judge-acceptance-local"},
            json=record["retrieval_request"],
        )
        body = response.json()
        cases = ((body.get("data") or {}).get("cases") or []) if isinstance(body, dict) else []
        first = cases[0] if cases else {}
        expected_first = record["expected_first_case_id"]
        checks = {
            "http_200": response.status_code == 200,
            "first_hit_matches": first.get("case_id") == expected_first,
            "candidate_data_true": first.get("candidate_data") is True,
            "approved_for_rag_false": (
                first.get("approved_for_rag") is False
                or (
                    first.get("owner_approved") is True
                    and first.get("source_verification_status") != "source_verified"
                )
            ),
            "source_boundary_present": bool(first.get("source_verification_status")),
        }
        observed.append(
            {
                "case_id": record["case_id"],
                "request": record["retrieval_request"],
                "expected_first_case_id": expected_first,
                "actual_first_case_id": first.get("case_id"),
                "actual_first_title": first.get("title"),
                "score": first.get("score"),
                "returned_case_ids": [item.get("case_id") for item in cases],
                "candidate_data": first.get("candidate_data"),
                "approved_for_rag": first.get("approved_for_rag"),
                "source_verification_status": first.get("source_verification_status"),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    rag_passed = (
        health.get("status") == "ok"
        and health.get("index_scope") == "candidate"
        and len(observed) == 3
        and all(item["passed"] for item in observed)
    )
    return {
        "validation_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_schema_id": payload.get("schema_id"),
        "health": health,
        "rag_acceptance": {
            "passed": rag_passed,
            "passed_count": sum(item["passed"] for item in observed),
            "total": len(observed),
            "records": observed,
        },
        "output_contract_validation": {
            "passed": not contract_errors,
            "errors": contract_errors,
        },
        "external_audit_and_feishu": {
            "executed": False,
            "status": "not_in_this_repository",
            "note": "The /audit rule engine, DeepSeek call, Feishu cards and legal workbench must be tested in the deployed integration; this report does not claim those external responses were observed.",
        },
        "overall_local_acceptance_passed": rag_passed and not contract_errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = execute_acceptance(payload, data_dir=args.data_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    passed = report["overall_local_acceptance_passed"]
    count = report["rag_acceptance"]["passed_count"]
    total = report["rag_acceptance"]["total"]
    print(f"Judge acceptance: {count}/{total} RAG cases passed; overall={passed}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
