import argparse
import os
from pathlib import Path

from src.api import (
    DEFAULT_DATA_DIR,
    CaseRepository,
    find_case,
    scope_of,
)
from src.build_chunks import (
    is_demo_production_chunk,
    production_exclusion_reasons,
)


def resolve_raw_text_path(data_dir: Path, raw_text_path: str) -> Path:
    path = Path(raw_text_path)
    return path if path.is_absolute() else data_dir.parent / path


def check_production_readiness(
    data_dir: Path,
    index_scope: str,
    api_key: str,
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if index_scope != "production":
        errors.append("CASE_ENGINE_INDEX_SCOPE 必须为 production")
    if not api_key:
        errors.append("ADSURE_API_KEY 未配置")

    try:
        repository = CaseRepository(data_dir, index_scope)
    except ValueError as exc:
        return {
            "index_scope": index_scope,
            "case_count": 0,
            "chunk_count": 0,
            "index_version": None,
        }, errors + [str(exc)]

    if repository.load_error:
        errors.append(f"索引加载失败：{repository.load_error}")
    if not repository.chunks:
        errors.append("正式索引为空")

    indexed_case_ids: set[str] = set()
    public_case_ids: set[str] = set()
    checked_raw_paths: set[str] = set()
    for chunk in repository.chunks:
        chunk_id = str(chunk.get("chunk_id") or "<missing>")
        case = find_case(repository.cases, chunk)
        if case is None:
            errors.append(f"切片未找到结构化案例：{chunk_id}")
            continue

        case_id = str(case.get("case_id") or "<missing>")
        indexed_case_ids.add(case_id)
        if scope_of(case, chunk) == "public":
            public_case_ids.add(case_id)

        reasons = (
            []
            if is_demo_production_chunk(chunk)
            else production_exclusion_reasons(case)
        )
        if reasons:
            errors.append(f"案例不满足 production 门禁：{case_id} ({', '.join(reasons)})")

        raw_text_path = str(case.get("raw_text_path") or "")
        if raw_text_path and raw_text_path not in checked_raw_paths:
            checked_raw_paths.add(raw_text_path)
            if not resolve_raw_text_path(data_dir, raw_text_path).is_file():
                errors.append(f"案例原文不存在：{case_id} ({raw_text_path})")

    if repository.chunks and not public_case_ids:
        errors.append("正式索引没有可供 /cases/retrieve 使用的公共案例")

    summary = {
        "index_scope": repository.scope,
        "case_count": len(indexed_case_ids),
        "public_case_count": len(public_case_ids),
        "chunk_count": len(repository.chunks),
        "index_version": repository.index_version or None,
    }
    return summary, list(dict.fromkeys(errors))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 Adsure RAG 生产启动条件")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.getenv("CASE_ENGINE_DATA_DIR", DEFAULT_DATA_DIR)),
    )
    parser.add_argument(
        "--index-scope",
        default=os.getenv("CASE_ENGINE_INDEX_SCOPE", "production"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.getenv("ADSURE_API_KEY") or os.getenv("CASE_ENGINE_API_KEY", "")
    summary, errors = check_production_readiness(
        args.data_dir,
        args.index_scope,
        api_key,
    )
    if errors:
        print("RAG production preflight failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "RAG production preflight ok:",
        f"cases={summary['case_count']}",
        f"public_cases={summary['public_case_count']}",
        f"chunks={summary['chunk_count']}",
        f"index={summary['index_version']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
