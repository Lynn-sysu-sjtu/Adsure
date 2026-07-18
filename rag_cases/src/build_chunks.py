import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_STRUCTURED_DIR = Path("data/structured")
DEFAULT_STRUCTURED_CANDIDATES_DIR = Path("data/structured_candidates")
DEFAULT_STRUCTURED_SAMPLES_DIR = Path("data/structured_samples")
DEFAULT_CHUNKS_DIR = Path("data/chunks")
DEFAULT_REPORTS_DIR = Path("data/reports")

MANUAL_CANDIDATE_SOURCE_TYPE = "manual_compilation_pending_source_verification"
SECTOR_CANDIDATE_SOURCE_TYPE = "manual_docx_sector_report_pending_source_verification"
OFFLINE_SAMPLE_SOURCE_TYPE = "offline_sample"


def unique_list(values: list) -> list:
    return list(dict.fromkeys(values))


def base_metadata(case: dict) -> dict:
    return {
        "source_type": case.get("source_type", ""),
        "sector": case.get("sector", ""),
        "sector_cn": case.get("sector_cn", ""),
        "violation_type": case.get("violation_type", ""),
        "case_nature": case.get("case_nature", ""),
        "source_verification_status": case.get("source_verification_status", ""),
        "approved_for_rag": approved_for_rag(case),
        "penalty_authority": case.get("penalty_authority", ""),
        "party_name": case.get("party_name", ""),
        "case_number": case.get("case_number", ""),
        "court": case.get("court", ""),
        "decision_date": case.get("decision_date", ""),
        "industry": case.get("industry", ""),
        "product_or_service": case.get("product_or_service", ""),
        "ad_channel": case.get("ad_channel", ""),
        "penalty_amount": case.get("penalty_amount"),
        "review_status": case.get("review_status", ""),
        "raw_text_path": case.get("raw_text_path", ""),
    }


def chunk_from_case(case: dict, chunk_type: str, text: str) -> dict:
    chunk_id = f"{case['case_id']}__{chunk_type}"
    chunk = {
        "chunk_id": chunk_id,
        "case_id": case["case_id"],
        "chunk_type": chunk_type,
        "title": case.get("title", ""),
        "source_name": case.get("source_name", ""),
        "source_url": case.get("source_url", ""),
        "risk_dimensions": unique_list(case.get("risk_dimensions", [])),
        "keywords": unique_list(case.get("keywords", [])),
        "text": text,
        "metadata": base_metadata(case),
    }
    if case.get("source_type") == SECTOR_CANDIDATE_SOURCE_TYPE:
        chunk.update(
            {
                "sector": case.get("sector"),
                "sector_cn": case.get("sector_cn"),
                "violation_type": case.get("violation_type"),
                "case_nature": case.get("case_nature"),
                "legal_basis": case.get("legal_basis", []),
                "illegal_claims": case.get("illegal_claims", []),
                "regulatory_logic": case.get("regulatory_logic", ""),
                "vector_text": case.get("vector_text", ""),
                "source_verification_status": case.get("source_verification_status", ""),
                "approved_for_rag": approved_for_rag(case),
            }
        )
    return chunk


def chunks_from_case(case: dict) -> list[dict]:
    chunks = []
    if case.get("vector_text"):
        chunks.append(chunk_from_case(case, "case_summary", case["vector_text"]))
    if case.get("regulatory_logic"):
        claims = "；".join(case.get("illegal_claims") or [])
        logic_text = (
            f"{case.get('title', '')}的监管逻辑：{case.get('regulatory_logic', '')}"
            f" 相关广告宣称：{claims}。"
        )
        chunks.append(chunk_from_case(case, "regulatory_logic", logic_text))
    return chunks


def load_existing(chunks_path: Path) -> dict[str, dict]:
    if not chunks_path.exists():
        return {}
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    return {chunk["chunk_id"]: chunk for chunk in chunks}


def valid_source_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def approved_for_rag(case: dict) -> bool:
    audit = case.get("audit") or {}
    return bool(case.get("approved_for_rag") is True or audit.get("approved_for_rag") is True)


def review_status(case: dict) -> str:
    audit = case.get("audit") or {}
    return audit.get("review_status") or case.get("review_status", "")


def has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value)
    return True


def production_exclusion_reasons(case: dict) -> list[str]:
    reasons = []
    source_type = case.get("source_type")
    if source_type == OFFLINE_SAMPLE_SOURCE_TYPE:
        reasons.append("source_type_offline_sample")
    if source_type == MANUAL_CANDIDATE_SOURCE_TYPE:
        reasons.append("source_type_manual_compilation_pending_source_verification")
    if source_type == SECTOR_CANDIDATE_SOURCE_TYPE:
        reasons.append("source_type_manual_docx_sector_report_pending_source_verification")
    if not valid_source_url(case.get("source_url")):
        reasons.append("source_url_not_verified_http_https")
    if case.get("source_verification_status") != "source_verified":
        reasons.append("source_verification_status_not_source_verified")
    if not approved_for_rag(case):
        reasons.append("audit_not_approved_for_rag")
    if review_status(case) not in {"approved", "reviewed"}:
        reasons.append("review_status_not_approved_or_reviewed")
    for field in ["legal_basis", "illegal_claims", "regulatory_logic"]:
        if not has_value(case.get(field)):
            reasons.append(f"missing_{field}")
    return reasons


def load_cases(directory: Path) -> list[tuple[Path, dict]]:
    if not directory.exists():
        return []
    cases = []
    for path in sorted(directory.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if case.get("exclude_from_validation") is True:
            continue
        cases.append((path, case))
    return cases


def render_chunk_report(report_rows: list[dict], totals: dict) -> str:
    lines = [
        "# Chunk Build Report",
        "",
        f"- Test chunks: {totals['test_chunks']}",
        f"- Candidate chunks: {totals['candidate_chunks']}",
        f"- Sector candidate chunks: {totals['sector_candidate_chunks']}",
        f"- Production chunks: {totals['production_chunks']}",
        "",
        "| case_id | source_type | destinations | production_reasons | path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report_rows:
        destinations = ", ".join(row["destinations"]) if row["destinations"] else "-"
        reasons = ", ".join(row["production_reasons"]) if row["production_reasons"] else "-"
        lines.append(
            f"| {row['case_id']} | {row['source_type']} | {destinations} | {reasons} | {row['path']} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(
    structured_dir: Path = DEFAULT_STRUCTURED_DIR,
    structured_candidates_dir: Path = DEFAULT_STRUCTURED_CANDIDATES_DIR,
    structured_samples_dir: Path = DEFAULT_STRUCTURED_SAMPLES_DIR,
    chunks_dir: Path = DEFAULT_CHUNKS_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
) -> dict[str, Path]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    test_chunks_by_id: dict[str, dict] = {}
    candidate_chunks_by_id: dict[str, dict] = {}
    sector_candidate_chunks_by_id: dict[str, dict] = {}
    production_chunks_by_id: dict[str, dict] = {}
    report_rows: list[dict] = []

    for source_dir, default_group in [
        (structured_samples_dir, "offline_sample"),
        (structured_candidates_dir, "candidate"),
        (structured_dir, "production"),
    ]:
        for case_path, case in load_cases(source_dir):
            source_type = case.get("source_type", default_group)
            chunks = chunks_from_case(case)
            destinations = []
            if source_type == OFFLINE_SAMPLE_SOURCE_TYPE or default_group == "offline_sample":
                destinations.append("test_chunks")
                for chunk in chunks:
                    test_chunks_by_id[chunk["chunk_id"]] = chunk
            if source_type == MANUAL_CANDIDATE_SOURCE_TYPE or (
                default_group == "candidate" and source_type != SECTOR_CANDIDATE_SOURCE_TYPE
            ):
                destinations.append("candidate_chunks")
                for chunk in chunks:
                    candidate_chunks_by_id[chunk["chunk_id"]] = chunk
            if source_type == SECTOR_CANDIDATE_SOURCE_TYPE:
                destinations.append("sector_candidate_chunks")
                for chunk in chunks:
                    sector_candidate_chunks_by_id[chunk["chunk_id"]] = chunk

            reasons = production_exclusion_reasons(case)
            if not reasons:
                destinations.append("production_chunks")
                for chunk in chunks:
                    production_chunks_by_id[chunk["chunk_id"]] = chunk

            report_rows.append(
                {
                    "case_id": case.get("case_id", case_path.stem),
                    "source_type": source_type,
                    "destinations": destinations,
                    "production_reasons": reasons,
                    "path": str(case_path),
                }
            )

    paths = {
        "test": chunks_dir / "test_chunks.json",
        "candidate": chunks_dir / "candidate_chunks.json",
        "sector_candidate": chunks_dir / "sector_candidate_chunks.json",
        "production": chunks_dir / "production_chunks.json",
    }
    payloads = {
        "test": sorted(test_chunks_by_id.values(), key=lambda item: item["chunk_id"]),
        "candidate": sorted(candidate_chunks_by_id.values(), key=lambda item: item["chunk_id"]),
        "sector_candidate": sorted(sector_candidate_chunks_by_id.values(), key=lambda item: item["chunk_id"]),
        "production": sorted(production_chunks_by_id.values(), key=lambda item: item["chunk_id"]),
    }
    for key, path in paths.items():
        path.write_text(json.dumps(payloads[key], ensure_ascii=False, indent=2), encoding="utf-8")

    totals = {
        "test_chunks": len(payloads["test"]),
        "candidate_chunks": len(payloads["candidate"]),
        "sector_candidate_chunks": len(payloads["sector_candidate"]),
        "production_chunks": len(payloads["production"]),
    }
    (reports_dir / "chunk_build_report.md").write_text(
        render_chunk_report(report_rows, totals),
        encoding="utf-8",
    )
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Build RAG chunks from structured cases.")
    parser.add_argument("--structured-dir", type=Path, default=DEFAULT_STRUCTURED_DIR)
    parser.add_argument("--structured-candidates-dir", type=Path, default=DEFAULT_STRUCTURED_CANDIDATES_DIR)
    parser.add_argument("--structured-samples-dir", type=Path, default=DEFAULT_STRUCTURED_SAMPLES_DIR)
    parser.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    args = parser.parse_args()

    paths = run(
        structured_dir=args.structured_dir,
        structured_candidates_dir=args.structured_candidates_dir,
        structured_samples_dir=args.structured_samples_dir,
        chunks_dir=args.chunks_dir,
        reports_dir=args.reports_dir,
    )
    print(json.dumps({key: str(path) for key, path in paths.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
