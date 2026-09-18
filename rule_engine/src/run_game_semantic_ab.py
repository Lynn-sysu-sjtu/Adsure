# -*- coding: utf-8 -*-
"""Run the game-only semantic recall A/B phases with UID-primary scoring."""

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch

from run_three_dataset_baseline import _load_json_dataset, _sha256, run_baseline, save_report


PROJECT_BASE = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = PROJECT_BASE.parents[1]
DEFAULT_DATASET_PATH = WORKSPACE_BASE / "测试集" / "20260911游戏测试样例集.json"
DEFAULT_OUTPUT_DIR = PROJECT_BASE / "test_reports" / "game_semantic_optimization_20260917"
PHASES = {
    "A1": {"threshold": 0.82, "limit": 2},
    "A2": {"threshold": 0.55, "limit": 2},
    "A3": {"threshold": 0.55, "limit": 4},
}


def load_game_cases(dataset_path=DEFAULT_DATASET_PATH):
    path = Path(dataset_path)
    cases = _load_json_dataset(path, "游戏")
    expected_ids = [f"EVAL-GAME-{index:03d}" for index in range(1, 11)]
    actual_ids = [case.get("case_id") for case in cases]
    if actual_ids != expected_ids:
        raise ValueError(f"Expected ordered game cases {expected_ids}, got {actual_ids}")
    if sum(bool(case.get("expected", {}).get("must_recall_rule_uids")) for case in cases) != 8:
        raise ValueError("Expected exactly eight UID-scorable game cases.")
    for case in cases:
        case.setdefault("expected", {}).setdefault("must_recall_rule_uids", [])
        case["expected"].setdefault("must_not_recall_rule_uids", [])
    sources = [{
        "file": path.name,
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "kind": "game_json_uid_baseline",
    }]
    return cases, sources


def run_phase(
    phase,
    dataset_path=DEFAULT_DATASET_PATH,
    output_dir=DEFAULT_OUTPUT_DIR,
    runner=run_baseline,
    saver=save_report,
):
    phase = str(phase).upper()
    if phase not in PHASES:
        raise ValueError(f"Unknown phase: {phase}")
    config = PHASES[phase]
    cases, sources = load_game_cases(dataset_path)
    baseline_name = f"game_semantic_{phase}"
    environment = {
        "ADSURE_FALLBACK_SEMANTIC_THRESHOLD": str(config["threshold"]),
        "ADSURE_FALLBACK_SEMANTIC_LIMIT": str(config["limit"]),
    }
    with patch.dict(os.environ, environment, clear=False):
        report = runner(
            cases,
            sources,
            baseline_name=baseline_name,
            llm_backend="mock",
            semantic_backend="zhipu",
        )
    report["phase"] = phase
    report["phase_config"] = dict(config)
    report["scoring_identity"] = "rule_uid"
    report.setdefault("config", {}).update(environment)
    json_path, csv_path = saver(report, output_dir)
    return json_path, csv_path, report


def main():
    parser = argparse.ArgumentParser(description="Run one game semantic recall A/B phase.")
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    json_path, csv_path, report = run_phase(args.phase, args.dataset, args.output_dir)
    print(json.dumps(report.get("summary", {}), ensure_ascii=False, indent=2))
    print(f"json_report={json_path}")
    print(f"comparison_csv={csv_path}")


if __name__ == "__main__":
    main()