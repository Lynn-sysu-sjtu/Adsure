import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_STRUCTURED_DIR = Path("data/structured")
DEFAULT_STRUCTURED_CANDIDATES_DIR = Path("data/structured_candidates")
DEFAULT_STRUCTURED_SAMPLES_DIR = Path("data/structured_samples")
DEFAULT_REPORTS_DIR = Path("data/reports")
DEFAULT_PROMPT_PATH = Path("prompts/clean_case_prompt.md")

REQUIRED_FIELDS = [
    "case_id",
    "title",
    "source_name",
    "risk_dimensions",
    "facts_summary",
    "regulatory_logic",
    "vector_text",
]

MANUAL_CANDIDATE_SOURCE_TYPE = "manual_compilation_pending_source_verification"
SECTOR_CANDIDATE_SOURCE_TYPE = "manual_docx_sector_report_pending_source_verification"
OFFLINE_SAMPLE_SOURCE_TYPE = "offline_sample"


def has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def valid_source_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def load_risk_dimensions(prompt_path: Path = DEFAULT_PROMPT_PATH) -> set[str]:
    text = prompt_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    risks: set[str] = set()
    in_enum = False
    for line in lines:
        stripped = line.strip()
        if "risk_dimensions 枚举" in stripped:
            in_enum = True
            continue
        if not in_enum:
            continue
        if stripped.startswith("- "):
            risks.add(stripped[2:].strip())
            continue
        if risks and not stripped:
            break
        if risks and stripped.endswith("："):
            break
    return risks


def chinese_char_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def looks_like_keyword_list(text: str) -> bool:
    segments = [part.strip() for part in re.split(r"[，,、；;]", text) if part.strip()]
    if len(segments) < 3:
        return False
    if any(mark in text for mark in "。！？!?"):
        return False
    return all(chinese_char_count(segment) <= 8 for segment in segments)


def valid_vector_text(text: str) -> bool:
    return chinese_char_count(text) >= 30 and not looks_like_keyword_list(text)


def audit_review_status(case: dict) -> str:
    audit = case.get("audit") or {}
    return audit.get("review_status") or case.get("review_status", "")


def approved_for_rag(case: dict) -> bool:
    audit = case.get("audit") or {}
    return bool(case.get("approved_for_rag") is True or audit.get("approved_for_rag") is True)


def case_group(case: dict, path_group: str) -> str:
    source_type = case.get("source_type")
    if source_type == SECTOR_CANDIDATE_SOURCE_TYPE:
        return "sector_candidate"
    if source_type == MANUAL_CANDIDATE_SOURCE_TYPE:
        return "candidate"
    if source_type == OFFLINE_SAMPLE_SOURCE_TYPE:
        return "offline_sample"
    return path_group


def validate_case(case: dict, allowed_risk_dimensions: set[str], group: str = "production") -> tuple[list[str], list[str]]:
    errors = []
    issues = []
    for field in REQUIRED_FIELDS:
        if not has_value(case.get(field)):
            errors.append(f"missing_required_field:{field}")

    source_url = case.get("source_url")
    if group in {"candidate", "sector_candidate"}:
        if not source_url:
            issues.append("source_url_missing_needs_verification")
        elif not valid_source_url(source_url):
            errors.append("invalid_source_url")
    elif group == "offline_sample":
        if not source_url:
            issues.append("offline_sample_source_url_missing")
    else:
        if not source_url:
            errors.append("missing_required_field:source_url")
        elif not valid_source_url(source_url):
            errors.append("invalid_source_url")

    if approved_for_rag(case) and not source_url:
        errors.append("approved_for_rag_without_source_url")

    if group == "sector_candidate":
        if case.get("source_verification_status") != "pending_source_lookup":
            errors.append("invalid_source_verification_status")
        if approved_for_rag(case):
            errors.append("sector_candidate_approved_for_rag")
        for field in ["case_nature", "sector", "violation_type"]:
            if not has_value(case.get(field)):
                errors.append(f"missing_required_field:{field}")
        if case.get("case_nature") == "civil_dispute_with_regulatory_signal" and (
            case.get("is_admin_penalty_candidate") is True
        ):
            errors.append("civil_dispute_misclassified_as_admin_penalty")

    risks = case.get("risk_dimensions") or []
    invalid_risks = [risk for risk in risks if allowed_risk_dimensions and risk not in allowed_risk_dimensions]
    if invalid_risks:
        errors.append(f"invalid_risk_dimensions:{','.join(invalid_risks)}")

    vector_text = case.get("vector_text") or ""
    if vector_text and not valid_vector_text(vector_text):
        errors.append("invalid_vector_text")

    if not has_value(case.get("legal_basis")):
        errors.append("missing_required_field:legal_basis")
    if not has_value(case.get("legal_basis")) and case.get("review_status") != "pending_review":
        errors.append("legal_basis_empty_requires_pending_review")

    if not has_value(case.get("illegal_claims")):
        issues.append("illegal_claims_missing_needs_review")
    if not has_value(case.get("mapped_rule_ids")):
        issues.append("needs_rule_mapping")
    if group == "production" and not has_value(case.get("violation_type")):
        issues.append("violation_type_missing_needs_review")

    return errors, issues


def render_markdown_report(report: dict) -> str:
    lines = [
        "# Validation Report",
        "",
        f"- Total: {report['total']}",
        f"- Valid: {report['valid_count']}",
        f"- Invalid: {report['invalid_count']}",
        f"- Needs Review: {report['needs_review_count']}",
        f"- Production cases: {report['production_count']}",
        f"- Candidate cases: {report['candidate_count']}",
        f"- Sector candidate cases: {report['sector_candidate_count']}",
        f"- Offline samples: {report['offline_sample_count']}",
        "",
        "## Case Details",
        "",
        "| case_id | status | group | errors | issues | path | review_status | needs_review |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["cases"]:
        status = "PASS" if item["valid"] else "FAIL"
        errors = ", ".join(item["errors"]) if item["errors"] else "-"
        issues = ", ".join(item["issues"]) if item["issues"] else "-"
        needs_review = "YES" if item["needs_review"] else "NO"
        lines.append(
            f"| {item['case_id']} | {status} | {item['group']} | {errors} | {issues} | {item['path']} | "
            f"{item['review_status']} | {needs_review} |"
        )
    lines.append("")
    return "\n".join(lines)


def load_cases_from_dir(directory: Path, path_group: str) -> list[tuple[Path, dict, str]]:
    if not directory.exists():
        return []
    cases = []
    for path in sorted(directory.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if case.get("exclude_from_validation") is True:
            continue
        cases.append((path, case, case_group(case, path_group)))
    return cases


def run(
    structured_dir: Path = DEFAULT_STRUCTURED_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    structured_candidates_dir: Path | None = None,
    structured_samples_dir: Path | None = None,
) -> dict:
    reports_dir.mkdir(parents=True, exist_ok=True)
    allowed_risk_dimensions = load_risk_dimensions(prompt_path)
    if structured_candidates_dir is None:
        structured_candidates_dir = structured_dir.parent / DEFAULT_STRUCTURED_CANDIDATES_DIR.name
    if structured_samples_dir is None:
        structured_samples_dir = structured_dir.parent / DEFAULT_STRUCTURED_SAMPLES_DIR.name

    cases = []
    all_cases = []
    all_cases.extend(load_cases_from_dir(structured_dir, "production"))
    all_cases.extend(load_cases_from_dir(structured_candidates_dir, "candidate"))
    all_cases.extend(load_cases_from_dir(structured_samples_dir, "offline_sample"))

    for path, case, group in all_cases:
        errors, issues = validate_case(case, allowed_risk_dimensions, group)
        review_status = audit_review_status(case)
        cases.append(
            {
                "case_id": case.get("case_id", path.stem),
                "group": group,
                "path": str(path),
                "valid": not errors,
                "errors": errors,
                "issues": issues,
                "review_status": review_status,
                "needs_review": bool(errors) or bool(issues) or review_status == "pending_review",
            }
        )
    report = {
        "total": len(cases),
        "valid_count": sum(1 for item in cases if item["valid"]),
        "invalid_count": sum(1 for item in cases if not item["valid"]),
        "needs_review_count": sum(1 for item in cases if item["needs_review"]),
        "production_count": sum(1 for item in cases if item["group"] == "production"),
        "candidate_count": sum(1 for item in cases if item["group"] == "candidate"),
        "sector_candidate_count": sum(1 for item in cases if item["group"] == "sector_candidate"),
        "offline_sample_count": sum(1 for item in cases if item["group"] == "offline_sample"),
        "cases": cases,
    }
    (reports_dir / "validation_report.md").write_text(render_markdown_report(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate structured case JSON files.")
    parser.add_argument("--structured-dir", type=Path, default=DEFAULT_STRUCTURED_DIR)
    parser.add_argument("--structured-candidates-dir", type=Path, default=DEFAULT_STRUCTURED_CANDIDATES_DIR)
    parser.add_argument("--structured-samples-dir", type=Path, default=DEFAULT_STRUCTURED_SAMPLES_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    args = parser.parse_args()

    report = run(
        structured_dir=args.structured_dir,
        reports_dir=args.reports_dir,
        prompt_path=args.prompt_path,
        structured_candidates_dir=args.structured_candidates_dir,
        structured_samples_dir=args.structured_samples_dir,
    )
    print(render_markdown_report(report))


if __name__ == "__main__":
    main()
