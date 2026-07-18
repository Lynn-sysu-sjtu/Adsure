# -*- coding: utf-8 -*-
"""Run local end-to-end rule engine baseline cases."""

import json
from pathlib import Path

from audit_api import audit_endpoint


PROJECT_BASE = Path(__file__).resolve().parents[1]
CASE_FILE = PROJECT_BASE / "test_cases" / "rule_engine_cases_v0.1.json"


def _load_cases():
    return json.loads(CASE_FILE.read_text(encoding="utf-8"))


def _ids(response_data):
    return {rule.get("rule_id") for rule in response_data.get("matched_rules", [])}


def _dimensions(response_data):
    return set(response_data.get("审核_推荐违规类型", []))


def _rule_by_id(response_data):
    return {rule.get("rule_id"): rule for rule in response_data.get("matched_rules", [])}


def _check_case(case):
    response = audit_endpoint(case["input_payload"], base_dir=PROJECT_BASE)
    if response.get("code") != 0:
        return [
            {
                "ok": False,
                "line": f"[FAIL] {case['case_id']} 引擎返回错误：{response.get('msg')}",
            }
        ]

    data = response["data"]
    expected = case["expected"]
    lines = []

    matched_ids = _ids(data)
    required_ids = set(expected.get("must_recall_rule_ids", []))
    missing_ids = sorted(required_ids - matched_ids)
    if missing_ids:
        lines.append(
            {
                "ok": False,
                "line": f"[FAIL] {case['case_id']} 未召回 {', '.join(missing_ids)}；实际命中 {', '.join(sorted(matched_ids)) or '无'}",
            }
        )
    else:
        lines.append(
            {
                "ok": True,
                "line": f"[PASS] {case['case_id']} 命中 {', '.join(sorted(required_ids))}",
            }
        )

    semantic_ids = set(expected.get("expected_semantic_rule_ids", []))
    if semantic_ids:
        matched_by_id = _rule_by_id(data)
        wrong_channel_ids = sorted(
            rule_id
            for rule_id in semantic_ids
            if matched_by_id.get(rule_id, {}).get("recall_channel") != "semantic"
        )
        if wrong_channel_ids:
            lines.append(
                {
                    "ok": False,
                    "line": f"[FAIL] {case['case_id']} ???????? {', '.join(wrong_channel_ids)}",
                }
            )
        else:
            lines.append(
                {
                    "ok": True,
                    "line": f"[PASS] {case['case_id']} semantic = {', '.join(sorted(semantic_ids))}",
                }
            )

    actual_dimensions = _dimensions(data)
    expected_dimensions = set(expected.get("expected_dimensions", []))
    missing_dimensions = sorted(expected_dimensions - actual_dimensions)
    if missing_dimensions:
        lines.append(
            {
                "ok": False,
                "line": f"[FAIL] {case['case_id']} 缺少违规维度 {', '.join(missing_dimensions)}；实际 {', '.join(sorted(actual_dimensions)) or '无'}",
            }
        )
    else:
        lines.append(
            {
                "ok": True,
                "line": f"[PASS] {case['case_id']} dimensions = {', '.join(sorted(expected_dimensions)) or '无'}",
            }
        )

    actual_risk = data.get("审核_推荐风险等级")
    expected_risk = expected.get("expected_risk_level")
    if actual_risk != expected_risk:
        lines.append(
            {
                "ok": False,
                "line": f"[FAIL] {case['case_id']} risk = {actual_risk}，预期 {expected_risk}",
            }
        )
    else:
        lines.append({"ok": True, "line": f"[PASS] {case['case_id']} risk = {actual_risk}"})

    actual_routing = data.get("routing")
    expected_routing = expected.get("expected_routing")
    if actual_routing != expected_routing:
        lines.append(
            {
                "ok": False,
                "line": f"[FAIL] {case['case_id']} routing = {actual_routing}，预期 {expected_routing}",
            }
        )
    else:
        lines.append({"ok": True, "line": f"[PASS] {case['case_id']} routing = {actual_routing}"})

    return lines


def run_cases():
    cases = _load_cases()
    all_lines = []
    for case in cases:
        all_lines.extend(_check_case(case))
    return all_lines


def main():
    lines = run_cases()
    passed = sum(1 for item in lines if item["ok"])
    failed = len(lines) - passed
    for item in lines:
        print(item["line"])
    print("-" * 72)
    print(f"Total checks: {len(lines)} | PASS: {passed} | FAIL: {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
