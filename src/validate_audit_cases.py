#!/usr/bin/env python3
"""Validate the standalone /audit material test dataset."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("data/audit_test_cases/real_mvp_cases_v0.1.json")
DEFAULT_CANDIDATES_DIR = Path("data/structured_candidates")
DEFAULT_REPORT = Path("data/reports/audit_test_case_validation_report.md")

INDUSTRIES = {"美妆", "保健食品", "游戏", "通用"}
URGENCIES = {"普通", "加急"}
MATERIAL_TYPES = {"图文", "短视频", "直播话术", "Banner", "详情页", "其他"}
RISK_LEVELS = {"高", "中", "低", "无明显风险"}
ROUTES = {"运营", "运营补资料", "法务"}
VIOLATION_TYPES = {
    "绝对化用语",
    "虚假宣传",
    "涉医疗宣传",
    "引证内容不规范",
    "广告可识别性不足",
    "价格促销误导",
    "用户评价/种草误导",
    "广告代言不合规",
    "未成年人保护",
    "平台准入/资质不符",
    "其他",
}


def validate_case(case: dict[str, Any], candidates_dir: Path) -> list[str]:
    errors: list[str] = []
    case_id = case.get("case_id")
    payload = case.get("input_payload")
    human = case.get("human_reference")
    provenance = case.get("provenance")

    if not isinstance(case_id, str) or not case_id:
        errors.append("case_id_missing")
    if not isinstance(case.get("case_name"), str) or not case.get("case_name"):
        errors.append("case_name_missing")
    if not isinstance(payload, dict):
        return errors + ["input_payload_invalid"]
    if not isinstance(human, dict):
        return errors + ["human_reference_invalid"]
    if not isinstance(provenance, dict):
        return errors + ["provenance_invalid"]

    for field in ("record_id", "mode", "industry", "content", "urgency", "supplement", "platform", "material_type", "product_category", "extras"):
        if field not in payload:
            errors.append(f"input_payload.{field}_missing")
    if payload.get("mode") != "标准":
        errors.append("mode_invalid")
    if payload.get("industry") not in INDUSTRIES:
        errors.append("industry_invalid")
    if payload.get("urgency") not in URGENCIES:
        errors.append("urgency_invalid")
    if payload.get("material_type") not in MATERIAL_TYPES:
        errors.append("material_type_invalid")
    if not isinstance(payload.get("content"), str) or not payload.get("content", "").strip():
        errors.append("content_invalid")
    if not isinstance(payload.get("platform"), list) or not payload.get("platform") or not all(isinstance(item, str) and item for item in payload.get("platform", [])):
        errors.append("platform_must_be_nonempty_array")
    if not isinstance(payload.get("extras"), dict):
        errors.append("extras_invalid")
    if any(key.startswith("expected_") or key == "human_reason" for key in payload):
        errors.append("human_answer_leaked_into_input_payload")

    if human.get("expected_risk_level") not in RISK_LEVELS:
        errors.append("expected_risk_level_invalid")
    if human.get("expected_routing") not in ROUTES:
        errors.append("expected_routing_invalid")
    violations = human.get("expected_violation_types")
    if not isinstance(violations, list) or any(item not in VIOLATION_TYPES for item in violations):
        errors.append("expected_violation_types_invalid")
    if not isinstance(human.get("human_reason"), str) or not human.get("human_reason", "").strip():
        errors.append("human_reason_missing")

    source_case_id = provenance.get("derived_from_case_id")
    source_path = candidates_dir / f"{source_case_id}.json"
    if not source_path.exists():
        errors.append("provenance_source_not_found")
    else:
        source = json.loads(source_path.read_text(encoding="utf-8"))
        if payload.get("content") not in (source.get("illegal_claims") or []):
            errors.append("content_not_exact_source_claim")
        if provenance.get("source_name") != source.get("source_name"):
            errors.append("provenance_source_name_mismatch")
    if provenance.get("source_verification_status") != "pending_source_lookup":
        errors.append("source_verification_status_must_be_pending_source_lookup")
    if provenance.get("approved_for_rag") is not False:
        errors.append("approved_for_rag_must_be_false")
    if provenance.get("source_url") is not None:
        errors.append("unverified_source_url_must_be_null")
    return errors


def validate_dataset(cases: Any, candidates_dir: Path) -> tuple[list[tuple[str, list[str]]], list[str]]:
    dataset_errors: list[str] = []
    if not isinstance(cases, list):
        return [], ["root_must_be_array"]
    if len(cases) != 20:
        dataset_errors.append(f"expected_20_cases_got_{len(cases)}")

    case_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    record_ids = [case.get("input_payload", {}).get("record_id") for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(set(case_ids)):
        dataset_errors.append("duplicate_case_id")
    if len(record_ids) != len(set(record_ids)):
        dataset_errors.append("duplicate_record_id")

    industries = Counter(case.get("input_payload", {}).get("industry") for case in cases if isinstance(case, dict))
    for industry in INDUSTRIES:
        if industries[industry] != 5:
            dataset_errors.append(f"industry_{industry}_expected_5_got_{industries[industry]}")

    case_results: list[tuple[str, list[str]]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            case_results.append((f"row_{index}", ["case_must_be_object"]))
            continue
        case_results.append((case.get("case_id") or f"row_{index}", validate_case(case, candidates_dir)))
    return case_results, dataset_errors


def write_report(
    cases: list[dict[str, Any]],
    case_results: list[tuple[str, list[str]]],
    dataset_errors: list[str],
    report_path: Path,
) -> None:
    failed = [(case_id, errors) for case_id, errors in case_results if errors]
    lines = [
        "# /audit 测试案例校验报告",
        "",
        f"- Total: {len(cases)}",
        f"- Valid: {len(cases) - len(failed)}",
        f"- Invalid: {len(failed)}",
        f"- Dataset errors: {len(dataset_errors)}",
        "",
    ]
    if dataset_errors:
        lines.extend(["## 数据集错误", "", *[f"- {error}" for error in dataset_errors], ""])
    if failed:
        lines.extend(["## 案例错误", ""])
        for case_id, errors in failed:
            lines.append(f"- `{case_id}`: {', '.join(errors)}")
    else:
        lines.extend(["所有案例均通过 schema、枚举、数量、来源回溯和原文一致性校验。", ""])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--candidates-dir", type=Path, default=DEFAULT_CANDIDATES_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = json.loads(args.input.read_text(encoding="utf-8"))
    case_results, dataset_errors = validate_dataset(cases, args.candidates_dir)
    write_report(cases, case_results, dataset_errors, args.report)
    failed_count = sum(bool(errors) for _, errors in case_results)
    print(f"Validated {len(cases)} /audit test cases: {failed_count} invalid")
    print(f"Validation report: {args.report}")
    return 1 if failed_count or dataset_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
