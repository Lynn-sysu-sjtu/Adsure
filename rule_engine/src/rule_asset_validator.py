# -*- coding: utf-8 -*-
"""Deterministic validation helpers for rule assets and references."""

import json


REPORT_KEYS = (
    "duplicate_rule_ids",
    "empty_rule_ids",
    "duplicate_scenario_ids",
    "orphan_vector_rule_ids",
    "orphan_test_expected_rule_ids",
    "orphan_group_rule_ids",
)


def _text(value):
    return str(value or "").strip()


def _semantic_scenarios(rule):
    recall = rule.get("recall") or {}
    scenarios = recall.get("semantic_scenarios") or []
    return scenarios if isinstance(scenarios, list) else []


def validate_rule_assets(
    rules,
    vector_rule_ids=None,
    expected_rule_ids=None,
    group_rule_ids=None,
):
    """Return stable validation findings without mutating the supplied rules."""
    by_id = {}
    empty_rule_ids = []
    duplicate_scenario_ids = []

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        rule_id = _text(rule.get("rule_id"))
        source_file = _text(rule.get("_source_file"))
        title = _text(rule.get("title"))
        if not rule_id:
            empty_rule_ids.append({"source_file": source_file, "title": title})
            continue
        by_id.setdefault(rule_id, []).append(rule)

        scenario_counts = {}
        for scenario in _semantic_scenarios(rule):
            if not isinstance(scenario, dict):
                continue
            scenario_id = _text(scenario.get("scenario_id"))
            if scenario_id:
                scenario_counts[scenario_id] = scenario_counts.get(scenario_id, 0) + 1
        for scenario_id, count in scenario_counts.items():
            if count > 1:
                duplicate_scenario_ids.append(
                    {
                        "rule_id": rule_id,
                        "scenario_id": scenario_id,
                        "source_file": source_file,
                    }
                )

    duplicate_rule_ids = []
    for rule_id, members in sorted(by_id.items()):
        if len(members) > 1:
            duplicate_rule_ids.append(
                {
                    "rule_id": rule_id,
                    "source_files": sorted(_text(item.get("_source_file")) for item in members),
                    "titles": sorted({_text(item.get("title")) for item in members}),
                }
            )

    known_rule_ids = set(by_id)
    return {
        "duplicate_rule_ids": duplicate_rule_ids,
        "empty_rule_ids": sorted(empty_rule_ids, key=lambda item: (item["source_file"], item["title"])),
        "duplicate_scenario_ids": sorted(
            duplicate_scenario_ids,
            key=lambda item: (item["rule_id"], item["scenario_id"], item["source_file"]),
        ),
        "orphan_vector_rule_ids": sorted(set(vector_rule_ids or ()) - known_rule_ids),
        "orphan_test_expected_rule_ids": sorted(set(expected_rule_ids or ()) - known_rule_ids),
        "orphan_group_rule_ids": sorted(set(group_rule_ids or ()) - known_rule_ids),
    }


def assert_valid_rule_assets(report):
    """Raise a readable error when any validation finding is present."""
    failures = {key: report.get(key) or [] for key in REPORT_KEYS if report.get(key)}
    if failures:
        raise ValueError("Invalid rule assets: " + json.dumps(failures, ensure_ascii=False))
