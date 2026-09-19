import argparse
import os
from pathlib import Path

from src.api import (
    DEFAULT_DATA_DIR,
    DEFAULT_MIN_SEMANTIC_SCORE,
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
    retrieval_mode: str = "lexical",
    min_semantic_score: float = DEFAULT_MIN_SEMANTIC_SCORE,
    require_semantic: bool = False,
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if index_scope != "production":
        errors.append("CASE_ENGINE_INDEX_SCOPE 必须为 production")
    if not api_key:
        errors.append("ADSURE_API_KEY 未配置")

    try:
        repository = CaseRepository(
            data_dir,
            index_scope,
            retrieval_mode=retrieval_mode,
            min_semantic_score=min_semantic_score,
        )
    except ValueError as exc:
        return {
            "index_scope": index_scope,
            "case_count": 0,
            "chunk_count": 0,
            "index_version": None,
            "requested_retrieval_mode": retrieval_mode,
            "effective_retrieval_mode": "lexical",
            "semantic_status": "unavailable",
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

    if (
        retrieval_mode in {"semantic", "hybrid"}
        and repository.semantic_index is not None
        and repository.semantic_status == "ready"
        and repository.chunks
    ):
        first_chunk_id = str(repository.chunks[0].get("chunk_id") or "")
        repository.semantic_index.scores("广告合规", {first_chunk_id})
        if repository.semantic_index.load_error:
            repository.semantic_status = (
                f"model_error:{repository.semantic_index.load_error}"
            )
            repository.effective_retrieval_mode = "lexical"

    if require_semantic and (
        repository.semantic_status != "ready"
        or repository.effective_retrieval_mode != retrieval_mode
    ):
        errors.append(
            "语义检索未就绪："
            f"requested={retrieval_mode}, status={repository.semantic_status}"
        )

    summary = {
        "index_scope": repository.scope,
        "case_count": len(indexed_case_ids),
        "public_case_count": len(public_case_ids),
        "chunk_count": len(repository.chunks),
        "index_version": repository.index_version or None,
        "requested_retrieval_mode": repository.requested_retrieval_mode,
        "effective_retrieval_mode": repository.effective_retrieval_mode,
        "semantic_status": repository.semantic_status,
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
    retrieval_mode = os.getenv("CASE_ENGINE_RETRIEVAL_MODE", "lexical").strip().lower()
    min_semantic_score = float(
        os.getenv("CASE_ENGINE_MIN_SEMANTIC_SCORE", str(DEFAULT_MIN_SEMANTIC_SCORE))
    )
    require_semantic = os.getenv("CASE_ENGINE_REQUIRE_SEMANTIC", "0") == "1"
    summary, errors = check_production_readiness(
        args.data_dir,
        args.index_scope,
        api_key,
        retrieval_mode,
        min_semantic_score,
        require_semantic,
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
        f"retrieval={summary['effective_retrieval_mode']}",
        f"semantic={summary['semantic_status']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
