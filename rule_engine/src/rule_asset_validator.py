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
    "duplicate_rule_uids",
    "empty_rule_uids",
    "orphan_vector_rule_uids",
    "orphan_group_rule_uids",
)

UID_ERROR_KEYS = (
    "duplicate_rule_uids",
    "empty_rule_uids",
    "orphan_vector_rule_uids",
    "orphan_group_rule_uids",
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
    vector_rule_uids=None,
    group_rule_uids=None,
):
    """Return stable validation findings without mutating supplied assets."""
    by_id = {}
    by_uid = {}
    empty_rule_ids = []
    empty_rule_uids = []
    duplicate_scenario_ids = []

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        rule_id = _text(rule.get("rule_id"))
        rule_uid = _text(rule.get("rule_uid"))
        source_file = _text(rule.get("_source_file"))
        title = _text(rule.get("title"))

        if rule_id:
            by_id.setdefault(rule_id, []).append(rule)
        else:
            empty_rule_ids.append({"source_file": source_file, "title": title})

        if rule_uid:
            by_uid.setdefault(rule_uid, []).append(rule)
        else:
            empty_rule_uids.append(
                {"source_file": source_file, "rule_id": rule_id, "title": title}
            )

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

    duplicate_rule_uids = []
    for rule_uid, members in sorted(by_uid.items()):
        if len(members) > 1:
            duplicate_rule_uids.append(
                {
                    "rule_uid": rule_uid,
                    "source_files": sorted(_text(item.get("_source_file")) for item in members),
                    "rule_ids": sorted({_text(item.get("rule_id")) for item in members}),
                }
            )

    known_rule_ids = set(by_id)
    known_rule_uids = set(by_uid)
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
        "duplicate_rule_uids": duplicate_rule_uids,
        "empty_rule_uids": sorted(
            empty_rule_uids,
            key=lambda item: (item["source_file"], item["rule_id"], item["title"]),
        ),
        "orphan_vector_rule_uids": sorted(set(vector_rule_uids or ()) - known_rule_uids),
        "orphan_group_rule_uids": sorted(set(group_rule_uids or ()) - known_rule_uids),
    }


def _raise_for_keys(report, keys):
    failures = {key: report.get(key) or [] for key in keys if report.get(key)}
    if failures:
        raise ValueError("Invalid rule assets: " + json.dumps(failures, ensure_ascii=False))


def assert_valid_rule_assets(report):
    """Raise when any legacy or UID validation finding is present."""
    _raise_for_keys(report, REPORT_KEYS)


def assert_valid_rule_uids(report):
    """Raise only for internal UID identity and UID reference failures."""
    _raise_for_keys(report, UID_ERROR_KEYS)