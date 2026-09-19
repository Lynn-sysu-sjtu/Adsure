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


def _embedding_expectations(
    provider: str,
    model: str,
    dimensions: int | None,
) -> tuple[str, str, int]:
    provider = (provider or "local").strip().lower()
    if provider == "zhipu":
        return provider, (model or "embedding-3").strip(), int(dimensions or 2048)
    return provider, (model or "BAAI/bge-base-zh-v1.5").strip(), int(dimensions or 768)


def check_production_readiness(
    data_dir: Path,
    index_scope: str,
    api_key: str,
    retrieval_mode: str = "lexical",
    min_semantic_score: float = DEFAULT_MIN_SEMANTIC_SCORE,
    require_semantic: bool = False,
    *,
    embedding_provider: str = "local",
    embedding_model: str = "",
    embedding_dimensions: int | None = None,
    embedding_api_key: str = "",
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if index_scope != "production":
        errors.append("CASE_ENGINE_INDEX_SCOPE 必须为 production")
    if not api_key:
        errors.append("ADSURE_API_KEY 未配置")

    provider, expected_model, expected_dimension = _embedding_expectations(
        embedding_provider,
        embedding_model,
        embedding_dimensions,
    )
    semantic_requested = retrieval_mode in {"semantic", "hybrid"}
    if semantic_requested and provider == "zhipu" and retrieval_mode != "hybrid":
        errors.append("CASE_ENGINE_EMBEDDING_PROVIDER=zhipu 时 CASE_ENGINE_RETRIEVAL_MODE 必须为 hybrid")
    if semantic_requested and provider == "zhipu" and not embedding_api_key:
        errors.append("CASE_ENGINE_EMBEDDING_PROVIDER=zhipu 但 ZHIPU_API_KEY/CASE_ENGINE_EMBEDDING_API_KEY 未配置")

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
            "embedding_provider": provider,
            "embedding_model": expected_model if semantic_requested else None,
            "embedding_dimension": expected_dimension if semantic_requested else None,
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

    index_model_mismatch = False
    index_dimension_mismatch = False
    if semantic_requested and repository.semantic_index is not None:
        actual_model = str(repository.semantic_index.model_name or "")
        actual_dimension = int(repository.semantic_index.dimension or 0)
        if actual_model != expected_model:
            index_model_mismatch = True
            errors.append(
                "语义索引模型不匹配："
                f"expected={expected_model}, actual={actual_model}"
            )
        if actual_dimension != expected_dimension:
            index_dimension_mismatch = True
            errors.append(
                "语义索引维度不匹配："
                f"expected={expected_dimension}, actual={actual_dimension}"
            )

    if repository.semantic_status.startswith("model_mismatch_index"):
        # CaseRepository 在 CASE_ENGINE_EMBEDDING_MODEL 与索引模型不一致时
        # 会直接丢弃索引，这里补一条明确的错误，避免只看到"语义检索未就绪"。
        index_model_mismatch = True
        errors.append(f"语义索引模型不匹配：{repository.semantic_status}")

    can_probe_semantic = (
        semantic_requested
        and repository.semantic_index is not None
        and repository.semantic_status == "ready"
        and repository.chunks
        and not index_model_mismatch
        and not index_dimension_mismatch
        and not (provider == "zhipu" and not embedding_api_key)
    )
    if can_probe_semantic:
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
        "embedding_provider": provider,
        "embedding_model": expected_model if semantic_requested else None,
        "embedding_dimension": expected_dimension if semantic_requested else None,
        "semantic_index_model": (
            repository.semantic_index.model_name
            if repository.semantic_index is not None
            else None
        ),
        "semantic_index_dimension": (
            repository.semantic_index.dimension
            if repository.semantic_index is not None
            else None
        ),
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
    embedding_provider = os.getenv("CASE_ENGINE_EMBEDDING_PROVIDER", "local").strip().lower()
    embedding_model = os.getenv("CASE_ENGINE_EMBEDDING_MODEL", "").strip()
    raw_dimensions = os.getenv("CASE_ENGINE_EMBEDDING_DIMENSIONS", "").strip()
    embedding_dimensions = int(raw_dimensions) if raw_dimensions else None
    embedding_api_key = (
        os.getenv("ZHIPU_API_KEY")
        or os.getenv("CASE_ENGINE_EMBEDDING_API_KEY", "")
    )
    require_semantic = (
        os.getenv("CASE_ENGINE_REQUIRE_SEMANTIC", "0") == "1"
        or (retrieval_mode in {"semantic", "hybrid"} and embedding_provider == "zhipu")
    )
    summary, errors = check_production_readiness(
        args.data_dir,
        args.index_scope,
        api_key,
        retrieval_mode,
        min_semantic_score,
        require_semantic,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dimensions=embedding_dimensions,
        embedding_api_key=embedding_api_key,
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
        f"provider={summary['embedding_provider']}",
        f"model={summary['embedding_model']}",
        f"dimension={summary['embedding_dimension']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
