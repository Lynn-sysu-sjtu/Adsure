import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.build_chunks import production_exclusion_reasons
from src.test_retrieval import bm25_scores, tokenize


LOGGER = logging.getLogger("adsure.rag")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
SUPPORTED_INDUSTRIES = {"美妆", "游戏", "保健食品", "通用"}
SUPPORTED_INDEX_SCOPES = {"production", "candidate"}
GENERIC_RETRIEVAL_TOKENS = {
    "广告",
    "内容",
    "行业",
    "平台",
    "投放",
    "相关",
    "案例",
    "违规",
    "违法",
    "监管",
    "通用",
    "未指",
    "指定",
}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DEFAULT_MIN_RELATIVE_SCORE = 0.25


def error_response(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": -1, "msg": message, "data": None},
    )


def retrieval_unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "code": -1,
            "msg": "案例检索服务暂不可用",
            "data": {"cases": []},
        },
    )


def approved_for_rag(case: dict) -> bool:
    audit = case.get("audit") or {}
    return bool(case.get("approved_for_rag") is True or audit.get("approved_for_rag") is True)


def review_status(case: dict) -> str:
    audit = case.get("audit") or {}
    return audit.get("review_status") or case.get("review_status", "")


def index_paths(data_dir: Path, scope: str) -> list[Path]:
    if scope == "production":
        return [data_dir / "chunks" / "production_chunks.json"]
    return [
        data_dir / "chunks" / "candidate_chunks.json",
        data_dir / "chunks" / "sector_candidate_chunks.json",
    ]


def structured_paths(data_dir: Path, scope: str) -> list[Path]:
    if scope == "production":
        return [data_dir / "structured"]
    return [data_dir / "structured_candidates"]


def load_chunks(data_dir: Path, scope: str) -> list[dict]:
    chunks_by_id: dict[str, dict] = {}
    for path in index_paths(data_dir, scope):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"切片索引格式错误：{path}")
        for chunk in payload:
            if isinstance(chunk, dict) and chunk.get("chunk_id"):
                chunks_by_id[chunk["chunk_id"]] = chunk
    return list(chunks_by_id.values())


def load_cases(data_dir: Path, scope: str) -> dict[tuple[str, str], dict]:
    cases: dict[tuple[str, str], dict] = {}
    for directory in structured_paths(data_dir, scope):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            case_id = case.get("case_id")
            if not case_id:
                continue
            source_type = case.get("source_type", "")
            cases[(case_id, source_type)] = case
    return cases


def index_version(scope: str, chunks: list[dict], cases: dict[tuple[str, str], dict]) -> str:
    payload = {
        "scope": scope,
        "chunks": chunks,
        "cases": sorted(
            {
                (case_id, source_type)
                for case_id, source_type in cases
            }
        ),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def find_case(cases: dict[tuple[str, str], dict], chunk: dict) -> dict | None:
    case_id = chunk.get("case_id", "")
    source_type = (chunk.get("metadata") or {}).get("source_type", "")
    exact = cases.get((case_id, source_type))
    if exact is not None:
        return exact
    matches = [case for (candidate_id, _), case in cases.items() if candidate_id == case_id]
    return matches[0] if len(matches) == 1 else None


def validate_payload(payload: Any, max_content_length: int) -> tuple[dict | None, str | None]:
    if not isinstance(payload, dict):
        return None, "请求体必须是 JSON 对象"

    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, "缺少必填字段：content"
    content = content.strip()
    if len(content) > max_content_length:
        return None, f"content 长度不能超过 {max_content_length}"

    industry = payload.get("industry")
    if isinstance(industry, str):
        industry = industry.strip()
    if not isinstance(industry, str) or industry not in SUPPORTED_INDUSTRIES:
        return None, "industry 必须是：美妆、游戏、保健食品或通用"

    platform = payload.get("platform", [])
    if not isinstance(platform, list) or any(not isinstance(item, str) for item in platform):
        return None, "platform 必须是字符串数组"

    top_k = payload.get("top_k", 3)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 5:
        return None, "top_k 必须是 1—5 的整数"

    return {
        "content": content,
        "industry": industry,
        "platform": platform,
        "top_k": top_k,
    }, None


def validate_search_payload(
    payload: Any,
    max_content_length: int,
) -> tuple[dict | None, str | None]:
    if not isinstance(payload, dict):
        return None, "请求体必须是 JSON 对象"

    tenant_id = payload.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        return None, "缺少必填字段：tenant_id"
    tenant_id = tenant_id.strip()
    if len(tenant_id) > 128:
        return None, "tenant_id 长度不能超过 128"

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        return None, "缺少必填字段：query"
    query = query.strip()
    if len(query) > max_content_length:
        return None, f"query 长度不能超过 {max_content_length}"

    industry = payload.get("industry")
    if not isinstance(industry, str) or not industry.strip():
        return None, "缺少必填字段：industry"
    industry = industry.strip()

    risk_level = payload.get("risk_level", "")
    if risk_level is None:
        risk_level = ""
    if not isinstance(risk_level, str):
        return None, "risk_level 必须是字符串"

    opinion_type = payload.get("opinion_type", "")
    if opinion_type is None:
        opinion_type = ""
    if not isinstance(opinion_type, str):
        return None, "opinion_type 必须是字符串"

    matched_rules = payload.get("matched_rules", [])
    if not isinstance(matched_rules, list):
        return None, "matched_rules 必须是数组"
    normalized_rules = []
    for index, rule in enumerate(matched_rules):
        if not isinstance(rule, dict):
            return None, f"matched_rules[{index}] 必须是对象"
        rule_id = rule.get("rule_id", "")
        dimension = rule.get("dimension", "")
        if rule_id is None:
            rule_id = ""
        if dimension is None:
            dimension = ""
        if not isinstance(rule_id, str) or not isinstance(dimension, str):
            return None, f"matched_rules[{index}] 的 rule_id 和 dimension 必须是字符串"
        normalized_rules.append(
            {"rule_id": rule_id.strip(), "dimension": dimension.strip()}
        )

    top_k = payload.get("top_k", 3)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
        return None, "top_k 必须是 1—20 的整数"

    return {
        "tenant_id": tenant_id,
        "query": query,
        "industry": industry,
        "risk_level": risk_level.strip(),
        "opinion_type": opinion_type.strip(),
        "matched_rules": normalized_rules,
        "top_k": top_k,
    }, None


def build_query(payload: dict) -> str:
    parts = [payload["industry"]]
    parts.extend(item.strip() for item in payload["platform"] if item.strip())
    parts.append(payload["content"])
    return " ".join(parts)


def build_search_query(payload: dict) -> str:
    parts = [payload["query"], payload["industry"]]
    parts.extend(
        rule["dimension"] for rule in payload["matched_rules"] if rule["dimension"]
    )
    parts.extend(rule["rule_id"] for rule in payload["matched_rules"] if rule["rule_id"])
    return " ".join(parts)


def best_chunks_by_case(
    query: str,
    chunks: list[dict],
    top_k: int,
    min_relative_score: float = DEFAULT_MIN_RELATIVE_SCORE,
) -> list[tuple[float, dict]]:
    best: dict[str, tuple[float, dict]] = {}
    for score, chunk in bm25_scores(query, chunks):
        if score <= 0 or not has_meaningful_overlap(query, str(chunk.get("text", ""))):
            continue
        case_id = chunk.get("case_id")
        if not case_id:
            continue
        current = best.get(case_id)
        if current is None or score > current[0]:
            best[case_id] = (score, chunk)
    ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
    if not ranked:
        return []
    minimum_score = ranked[0][0] * min_relative_score
    return [item for item in ranked if item[0] >= minimum_score][:top_k]


def has_meaningful_overlap(query: str, text: str) -> bool:
    query_tokens = {
        token
        for token in tokenize(query)
        if len(token) >= 2 and token not in GENERIC_RETRIEVAL_TOKENS
    }
    text_tokens = {
        token
        for token in tokenize(text)
        if len(token) >= 2 and token not in GENERIC_RETRIEVAL_TOKENS
    }
    return bool(query_tokens & text_tokens)


def lexical_cosine(left: str, right: str) -> float:
    left_counts = Counter(tokenize(left))
    right_counts = Counter(tokenize(right))
    if not left_counts or not right_counts:
        return 0.0
    numerator = sum(
        count * right_counts.get(token, 0)
        for token, count in left_counts.items()
    )
    left_norm = math.sqrt(sum(count * count for count in left_counts.values()))
    right_norm = math.sqrt(sum(count * count for count in right_counts.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if isinstance(value, str) and value:
        return [value]
    return []


def content_snippet(case: dict, chunk: dict) -> str:
    claims = normalize_string_list(case.get("illegal_claims"))
    text = "；".join(claims) if claims else str(chunk.get("text", ""))
    return text[:150]


def is_production_case(case: dict, _chunk: dict) -> bool:
    return not production_exclusion_reasons(case)


def adapt_case(score: float, chunk: dict, case: dict, candidate_data: bool) -> dict:
    metadata = chunk.get("metadata") or {}
    channel = case.get("ad_channel") or metadata.get("ad_channel")
    return {
        "case_id": case["case_id"],
        "title": case.get("title", ""),
        "content_snippet": content_snippet(case, chunk),
        "industry": case.get("industry") or metadata.get("industry", ""),
        "platform": normalize_string_list(channel),
        "violation_type": case.get("violation_type") or metadata.get("violation_type") or None,
        "risk_dimensions": normalize_string_list(case.get("risk_dimensions")),
        "risk_level": None,
        "ruling": case.get("penalty_result") or None,
        "legal_basis": normalize_string_list(case.get("legal_basis")),
        "regulatory_logic": case.get("regulatory_logic") or None,
        "score": round(score, 6),
        "score_type": "bm25",
        "similarity": None,
        "source_name": case.get("source_name", ""),
        "source_url": case.get("source_url"),
        "raw_text_path": case.get("raw_text_path", ""),
        "review_status": review_status(case),
        "source_verification_status": case.get("source_verification_status", ""),
        "approved_for_rag": approved_for_rag(case),
        "candidate_data": candidate_data,
    }


def scope_of(case: dict, chunk: dict) -> str:
    metadata = chunk.get("metadata") or {}
    return str(case.get("scope") or chunk.get("scope") or metadata.get("scope") or "public")


def tenant_id_of(case: dict, chunk: dict) -> str:
    metadata = chunk.get("metadata") or {}
    return str(
        case.get("tenant_id")
        or chunk.get("tenant_id")
        or metadata.get("tenant_id")
        or ""
    )


def visible_to_tenant(case: dict, chunk: dict, tenant_id: str | None) -> bool:
    scope = scope_of(case, chunk)
    if scope == "public":
        return True
    if scope == "tenant":
        owner_tenant_id = tenant_id_of(case, chunk)
        return bool(tenant_id and owner_tenant_id and tenant_id == owner_tenant_id)
    return False


def industry_group(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    if not normalized:
        return ""
    if normalized == "通用":
        return "general"
    if "游戏" in normalized or normalized == "game":
        return "game"
    if any(term in normalized for term in ("美妆", "化妆品", "医美", "美容")):
        return "beauty"
    if any(
        term in normalized
        for term in ("保健食品", "保健品", "普通食品", "健康产品", "食品")
    ) or normalized == "health":
        return "health_food"
    return ""


def case_matches_industry(request_industry: str | None, case: dict, chunk: dict) -> bool:
    requested_group = industry_group(request_industry)
    if requested_group in {"", "general"}:
        return True

    metadata = chunk.get("metadata") or {}
    case_groups = {
        industry_group(value)
        for value in (
            case.get("industry"),
            metadata.get("industry"),
            metadata.get("sector"),
            metadata.get("sector_cn"),
        )
    }
    case_groups.discard("")
    return requested_group in case_groups


def search_case_summary(case: dict, chunk: dict) -> str:
    summary = case.get("facts_summary")
    if not isinstance(summary, str) or not summary.strip():
        claims = normalize_string_list(case.get("illegal_claims") or chunk.get("illegal_claims"))
        summary = "；".join(claims) if claims else str(chunk.get("text", ""))
    summary = summary.strip()
    return summary if len(summary) <= 240 else summary[:239].rstrip() + "…"


def adapt_search_case(
    query: str,
    chunk: dict,
    case: dict,
    candidate_data: bool,
) -> dict:
    metadata = chunk.get("metadata") or {}
    return {
        "case_id": case["case_id"],
        "title": case.get("title", ""),
        "summary": search_case_summary(case, chunk),
        "penalty_result": case.get("penalty_result") or "",
        "source": case.get("source_name", ""),
        "similarity": round(lexical_cosine(query, str(chunk.get("text", ""))), 4),
        "source_url": case.get("source_url"),
        "candidate_data": candidate_data,
        "source_verification_status": (
            case.get("source_verification_status")
            or chunk.get("source_verification_status")
            or metadata.get("source_verification_status")
            or ""
        ),
    }


class CaseRepository:
    def __init__(
        self,
        data_dir: Path,
        scope: str,
        min_relative_score: float = DEFAULT_MIN_RELATIVE_SCORE,
    ):
        if scope not in SUPPORTED_INDEX_SCOPES:
            raise ValueError("CASE_ENGINE_INDEX_SCOPE 只能是 production 或 candidate")
        if not 0 <= min_relative_score <= 1:
            raise ValueError("CASE_ENGINE_MIN_RELATIVE_SCORE 必须在 0—1 之间")
        self.scope = scope
        self.candidate_data = scope == "candidate"
        self.min_relative_score = min_relative_score
        self.load_error = ""
        self.loaded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.index_version = ""
        try:
            self.chunks = load_chunks(data_dir, scope)
            self.cases = load_cases(data_dir, scope)
            self.index_version = index_version(scope, self.chunks, self.cases)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.chunks = []
            self.cases = {}
            self.load_error = f"{type(exc).__name__}: {exc}"

    def ranked_cases(
        self,
        query: str,
        top_k: int,
        tenant_id: str | None = None,
        request_industry: str | None = None,
    ) -> list[tuple[float, dict, dict]]:
        if self.load_error:
            return []
        visible_chunks = []
        for chunk in self.chunks:
            case = find_case(self.cases, chunk)
            if case is None:
                continue
            if not visible_to_tenant(case, chunk, tenant_id):
                continue
            if self.scope == "production" and not is_production_case(case, chunk):
                continue
            if not case_matches_industry(request_industry, case, chunk):
                continue
            visible_chunks.append(chunk)

        results = []
        for score, chunk in best_chunks_by_case(
            query,
            visible_chunks,
            top_k,
            self.min_relative_score,
        ):
            case = find_case(self.cases, chunk)
            if case is None:
                continue
            results.append((score, chunk, case))
        return results

    def retrieve(self, query: str, top_k: int, request_industry: str) -> list[dict]:
        return [
            adapt_case(score, chunk, case, self.candidate_data)
            for score, chunk, case in self.ranked_cases(
                query,
                top_k,
                request_industry=request_industry,
            )
        ]

    def search(
        self,
        query: str,
        top_k: int,
        tenant_id: str,
        request_industry: str,
    ) -> list[dict]:
        return [
            adapt_search_case(query, chunk, case, self.candidate_data)
            for _, chunk, case in self.ranked_cases(
                query,
                top_k,
                tenant_id,
                request_industry,
            )
        ]


def create_app(
    *,
    data_dir: Path | None = None,
    index_scope: str | None = None,
    api_key: str | None = None,
) -> FastAPI:
    resolved_data_dir = data_dir or Path(os.getenv("CASE_ENGINE_DATA_DIR", DEFAULT_DATA_DIR))
    resolved_scope = index_scope or os.getenv("CASE_ENGINE_INDEX_SCOPE", "production")
    resolved_key = (
        api_key
        if api_key is not None
        else os.getenv("ADSURE_API_KEY") or os.getenv("CASE_ENGINE_API_KEY", "")
    )
    max_content_length = int(os.getenv("CASE_ENGINE_MAX_CONTENT_LENGTH", "20000"))
    min_relative_score = float(
        os.getenv("CASE_ENGINE_MIN_RELATIVE_SCORE", str(DEFAULT_MIN_RELATIVE_SCORE))
    )
    repository = CaseRepository(
        resolved_data_dir,
        resolved_scope,
        min_relative_score,
    )

    application = FastAPI(title="Ads Penalty Case Retrieval API", version="1.0.0")
    application.state.api_key = resolved_key
    application.state.repository = repository

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid.uuid4().hex
        )
        request.state.request_id = request_id
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception(
                "request_failed request_id=%s method=%s path=%s",
                request_id,
                request.method,
                request.url.path,
            )
            raise
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response("请求体必须是有效 JSON 对象", 400)

    @application.get("/health")
    def health() -> dict:
        key_configured = bool(application.state.api_key)
        index_ready = not repository.load_error
        return {
            "status": "ok" if key_configured and index_ready else "degraded",
            "service": "adsure-rag",
            "index_scope": repository.scope,
            "candidate_data": repository.candidate_data,
            "case_count": len({chunk.get("case_id") for chunk in repository.chunks}),
            "chunk_count": len(repository.chunks),
            "index_version": repository.index_version or None,
            "loaded_at": repository.loaded_at,
            "checks": {
                "index": "ok" if index_ready else "error",
                "api_key": "configured" if key_configured else "missing",
            },
        }

    @application.post("/cases/retrieve", response_model=None)
    def retrieve_cases(
        request: Request,
        payload: Any = Body(...),
        x_api_key: str | None = Header(default=None),
    ):
        if not application.state.api_key:
            return error_response("服务端未配置 ADSURE_API_KEY", 503)
        if not x_api_key or not hmac.compare_digest(x_api_key, application.state.api_key):
            return error_response("API Key 无效或缺失", 401)

        validated, message = validate_payload(payload, max_content_length)
        if message:
            return error_response(message)

        if repository.load_error:
            return retrieval_unavailable_response()

        try:
            query = build_query(validated)
            cases = repository.retrieve(
                query,
                validated["top_k"],
                validated["industry"],
            )
        except Exception:
            # Related cases are an auxiliary feature. Return a stable, empty
            # payload with a non-success status so the caller can degrade
            # without confusing an infrastructure failure with "no matches".
            LOGGER.exception(
                "retrieval_failed request_id=%s index_version=%s",
                request.state.request_id,
                repository.index_version,
            )
            return retrieval_unavailable_response()

        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "cases": cases,
                "retrieval_meta": {
                    "index_scope": repository.scope,
                    "index_version": repository.index_version,
                    "top_k": validated["top_k"],
                    "returned": len(cases),
                },
            },
        }

    @application.post("/search", response_model=None)
    def search_cases(
        request: Request,
        payload: Any = Body(...),
        x_api_key: str | None = Header(default=None),
    ):
        if not application.state.api_key:
            return error_response("服务端未配置 ADSURE_API_KEY", 503)
        if not x_api_key or not hmac.compare_digest(x_api_key, application.state.api_key):
            return error_response("API Key 无效或缺失", 401)

        validated, message = validate_search_payload(payload, max_content_length)
        if message:
            return error_response(message)

        try:
            query = build_search_query(validated)
            cases = repository.search(
                query,
                validated["top_k"],
                validated["tenant_id"],
                validated["industry"],
            )
        except Exception:
            # RAG context is optional: retrieval failure must not erase the rule result.
            LOGGER.exception(
                "search_failed request_id=%s index_version=%s",
                request.state.request_id,
                repository.index_version,
            )
            cases = []

        return {
            "code": 0,
            "msg": "ok",
            "data": {
                "cases": cases,
                "meta": {
                    "index_scope": repository.scope,
                    "index_version": repository.index_version,
                    "candidate_data": repository.candidate_data,
                    "similarity_method": "lexical_cosine_v1",
                },
            },
        }

    return application


app = create_app()
