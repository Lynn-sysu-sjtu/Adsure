import argparse
import json
from pathlib import Path

from src.api import CaseRepository, build_query


DEFAULT_DATA_DIR = Path("data")
DEFAULT_EVALUATIONS_PATH = Path("data/evaluation/retrieval_quality_cases.json")
DEFAULT_JSON_REPORT = Path("data/reports/retrieval_quality_report.json")
DEFAULT_MARKDOWN_REPORT = Path("data/reports/retrieval_quality_report.md")


def retrieve(repository: CaseRepository, request: dict) -> list[dict]:
    channels = list(request.get("platform", []))
    if request.get("ad_channel"):
        channels.append(request["ad_channel"])
    return repository.retrieve(
        build_query(request),
        request.get("top_k", 3),
        request["industry"],
        product_category=request.get("product_category", ""),
        requested_channels=channels,
        risk_dimensions=request.get("risk_dimensions", []),
        matched_rule_ids=request.get("matched_rule_ids", []),
    )


def expected_for_mode(evaluation: dict, mode: str) -> tuple[str, str | list[str]]:
    if mode == "hybrid" and evaluation.get("expected_hybrid_first_case_id"):
        return "first", evaluation["expected_hybrid_first_case_id"]
    if evaluation.get("expected_first_case_id"):
        return "first", evaluation["expected_first_case_id"]
    return "exact", evaluation.get("expected_case_ids", [])


def evaluate_mode(
    mode: str,
    evaluations: list[dict],
    data_dir: Path,
) -> dict:
    repository = CaseRepository(
        data_dir,
        "production",
        retrieval_mode=mode,
    )
    rows = []
    passed = 0
    for evaluation in evaluations:
        results = retrieve(repository, evaluation["request"])
        case_ids = [result["case_id"] for result in results]
        expectation_type, expected = expected_for_mode(evaluation, mode)
        if expectation_type == "first":
            success = bool(case_ids) and case_ids[0] == expected
        else:
            success = case_ids == expected
        passed += int(success)
        rows.append(
            {
                "evaluation_id": evaluation["evaluation_id"],
                "expected_type": expectation_type,
                "expected": expected,
                "actual_case_ids": case_ids,
                "passed": success,
                "first_score": results[0]["score"] if results else None,
                "first_similarity": results[0]["similarity"] if results else None,
                "retrieval_method": (
                    results[0]["retrieval_method"]
                    if results
                    else (
                        "hybrid_rrf_v1"
                        if repository.effective_retrieval_mode == "hybrid"
                        else "fielded_bm25_v2"
                    )
                ),
            }
        )
    return {
        "requested_mode": mode,
        "effective_mode": repository.effective_retrieval_mode,
        "semantic_status": repository.semantic_status,
        "total": len(evaluations),
        "passed": passed,
        "pass_rate": round(passed / len(evaluations), 4) if evaluations else 0.0,
        "rows": rows,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Retrieval Quality Report",
        "",
        "> 小规模人工回归集，只用于防止已知问题复发，不代表全量生产准确率。",
        "",
        "| requested_mode | effective_mode | semantic_status | passed | total | pass_rate |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for result in report["modes"]:
        lines.append(
            f"| {result['requested_mode']} | {result['effective_mode']} | "
            f"{result['semantic_status']} | {result['passed']} | "
            f"{result['total']} | {result['pass_rate']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| mode | evaluation_id | expected | actual | passed | method | similarity |",
            "| --- | --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for result in report["modes"]:
        for row in result["rows"]:
            lines.append(
                f"| {result['requested_mode']} | {row['evaluation_id']} | "
                f"{row['expected']} | {row['actual_case_ids']} | "
                f"{'YES' if row['passed'] else 'NO'} | "
                f"{row['retrieval_method']} | "
                f"{row['first_similarity'] if row['first_similarity'] is not None else '-'} |"
            )
    return "\n".join(lines) + "\n"


def run(
    data_dir: Path = DEFAULT_DATA_DIR,
    evaluations_path: Path = DEFAULT_EVALUATIONS_PATH,
    json_report: Path = DEFAULT_JSON_REPORT,
    markdown_report: Path = DEFAULT_MARKDOWN_REPORT,
) -> dict:
    evaluations = json.loads(evaluations_path.read_text(encoding="utf-8"))
    report = {
        "evaluation_set": str(evaluations_path),
        "modes": [
            evaluate_mode("lexical", evaluations, data_dir),
            evaluate_mode("hybrid", evaluations, data_dir),
        ],
    }
    json_report.parent.mkdir(parents=True, exist_ok=True)
    markdown_report.parent.mkdir(parents=True, exist_ok=True)
    json_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_report.write_text(render_markdown(report), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate lexical and hybrid Adsure retrieval modes."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--evaluations",
        type=Path,
        default=DEFAULT_EVALUATIONS_PATH,
    )
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument(
        "--markdown-report",
        type=Path,
        default=DEFAULT_MARKDOWN_REPORT,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run(
        args.data_dir,
        args.evaluations,
        args.json_report,
        args.markdown_report,
    )
    print(
        " ".join(
            f"{mode['requested_mode']}={mode['passed']}/{mode['total']}"
            for mode in report["modes"]
        )
    )
    return 0 if all(mode["passed"] == mode["total"] for mode in report["modes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
