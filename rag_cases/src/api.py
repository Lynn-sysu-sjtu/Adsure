from __future__ import annotations

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

from src.build_chunks import (
    is_demo_production_chunk,
    load_case_record,
    production_exclusion_reasons,
)
from src.retrieval import (
    fielded_bm25_scores,
    informative_terms,
    tokenize,
)
from src.semantic_index import SemanticIndex, chunks_fingerprint
from src.platform_rules import PlatformRuleRepository
from src.audit_contract import build_response as build_audit_response, normalize_request as normalize_audit_request


LOGGER = logging.getLogger("adsure.rag")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
SUPPORTED_INDUSTRIES = {"美妆", "游戏", "保健食品", "通用"}
SUPPORTED_INDEX_SCOPES = {"production", "candidate"}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DEFAULT_MIN_RELATIVE_SCORE = 0.25
DEFAULT_MIN_QUERY_COVERAGE = 0.25
DEFAULT_MIN_SEMANTIC_SCORE = 0.62
MAX_CONSTRAINT_ITEMS = 20
SUPPORTED_RETRIEVAL_MODES = {"lexical", "semantic", "hybrid"}


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


def semantic_index_path(data_dir: Path, scope: str) -> Path:
    return data_dir / "chunks" / f"{scope}_semantic_index.json"


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


def load_cases(
    data_dir: Path,
    scope: str,
    indexed_case_ids: set[str] | None = None,
) -> dict[tuple[str, str], dict]:
    cases: dict[tuple[str, str], dict] = {}
    for directory in structured_paths(data_dir, scope):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            case = load_case_record(path)
            case_id = case.get("case_id")
            if not case_id:
                continue
            if indexed_case_ids is not None and case_id not in indexed_case_ids:
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

    normalized_lists: dict[str, list[str]] = {}
    for field in ("claim_spans", "risk_dimensions", "matched_rule_ids"):
        value = payload.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return None, f"{field} 必须是字符串数组"
        normalized = list(
            dict.fromkeys(item.strip() for item in value if item.strip())
        )
        if len(normalized) > MAX_CONSTRAINT_ITEMS:
            return None, f"{field} 最多包含 {MAX_CONSTRAINT_ITEMS} 项"
        normalized_lists[field] = normalized

    product_category = payload.get("product_category", "")
    if product_category is None:
        product_category = ""
    if not isinstance(product_category, str):
        return None, "product_category 必须是字符串"

    ad_channel = payload.get("ad_channel", "")
    if ad_channel is None:
        ad_channel = ""
    if not isinstance(ad_channel, str):
        return None, "ad_channel 必须是字符串"

    top_k = payload.get("top_k", 3)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 5:
        return None, "top_k 必须是 1—5 的整数"

    return {
        "content": content,
        "industry": industry,
        "platform": list(dict.fromkeys(item.strip() for item in platform if item.strip())),
        "claim_spans": normalized_lists["claim_spans"],
        "risk_dimensions": normalized_lists["risk_dimensions"],
        "matched_rule_ids": normalized_lists["matched_rule_ids"],
        "product_category": product_category.strip(),
        "ad_channel": ad_channel.strip(),
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
    parts = [payload["content"]]
    parts.extend(payload.get("claim_spans", []))
    parts.extend(payload.get("risk_dimensions", []))
    parts.extend(payload.get("matched_rule_ids", []))
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
    min_query_coverage: float = DEFAULT_MIN_QUERY_COVERAGE,
    semantic_index: SemanticIndex | None = None,
    retrieval_mode: str = "lexical",
    min_semantic_score: float = DEFAULT_MIN_SEMANTIC_SCORE,
) -> list[tuple[float, dict, dict]]:
    best: dict[str, tuple[float, dict, dict]] = {}
    query_term_count = len(informative_terms(query))
    minimum_matched_terms = 1 if query_term_count <= 3 else 2
    lexical_scored = fielded_bm25_scores(query, chunks)
    lexical_eligible = [
        scored
        for scored in lexical_scored
        if scored.score > 0
        and len(scored.matched_terms) >= minimum_matched_terms
        and scored.query_coverage >= min_query_coverage
    ]
    lexical_by_id = {
        str(scored.chunk.get("chunk_id")): scored
        for scored in lexical_eligible
    }
    lexical_ranks = {
        str(scored.chunk.get("chunk_id")): rank
        for rank, scored in enumerate(lexical_eligible, start=1)
    }

    semantic_by_id: dict[str, float] = {}
    semantic_ranks: dict[str, int] = {}
    if retrieval_mode in {"semantic", "hybrid"} and semantic_index is not None:
        semantic_scores = [
            scored
            for scored in semantic_index.scores(
                query,
                {
                    str(chunk.get("chunk_id"))
                    for chunk in chunks
                    if chunk.get("chunk_id")
                },
            )
            if scored.score >= min_semantic_score
        ]
        semantic_by_id = {
            scored.chunk_id: scored.score for scored in semantic_scores
        }
        semantic_ranks = {
            scored.chunk_id: rank
            for rank, scored in enumerate(semantic_scores, start=1)
        }

    if retrieval_mode == "lexical":
        candidate_ids = set(lexical_by_id)
    elif retrieval_mode == "semantic":
        candidate_ids = set(semantic_by_id)
    else:
        candidate_ids = set(lexical_by_id) | set(semantic_by_id)

    chunks_by_id = {
        str(chunk.get("chunk_id")): chunk
        for chunk in chunks
        if chunk.get("chunk_id")
    }
    rrf_k = 60
    maximum_rrf = 1 / (rrf_k + 1)
    for chunk_id in candidate_ids:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        lexical = lexical_by_id.get(chunk_id)
        semantic_score = semantic_by_id.get(chunk_id)
        lexical_rank = lexical_ranks.get(chunk_id)
        semantic_rank = semantic_ranks.get(chunk_id)
        if retrieval_mode == "lexical":
            final_score = lexical.score if lexical is not None else 0.0
            score_type = "bm25"
            method = "fielded_bm25_v2"
        elif retrieval_mode == "semantic":
            final_score = semantic_score or 0.0
            score_type = "semantic_cosine"
            method = "dense_semantic_v1"
        else:
            lexical_rrf = (
                1 / (rrf_k + lexical_rank)
                if lexical_rank is not None
                else 0.0
            )
            semantic_rrf = (
                1 / (rrf_k + semantic_rank)
                if semantic_rank is not None
                else 0.0
            )
            final_score = (
                0.55 * lexical_rrf + 0.45 * semantic_rrf
            ) / maximum_rrf
            score_type = "hybrid_rrf"
            method = "hybrid_rrf_v1"
        case_id = chunk.get("case_id")
        if not case_id:
            continue
        evidence = {
            "matched_terms": lexical.matched_terms[:12] if lexical else [],
            "matched_fields": lexical.matched_fields if lexical else [],
            "query_coverage": round(lexical.query_coverage, 4) if lexical else 0.0,
            "lexical_score": round(lexical.score, 6) if lexical else None,
            "semantic_similarity": (
                round(semantic_score, 6)
                if semantic_score is not None
                else None
            ),
            "fusion_score": (
                round(final_score, 6)
                if retrieval_mode == "hybrid"
                else None
            ),
            "score_type": score_type,
            "retrieval_method": method,
        }
        current = best.get(case_id)
        if current is None or final_score > current[0]:
            best[case_id] = (final_score, chunk, evidence)
    ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
    if not ranked:
        return []
    minimum_score = ranked[0][0] * min_relative_score
    return [item for item in ranked if item[0] >= minimum_score][:top_k]


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


def is_production_case(case: dict, chunk: dict) -> bool:
    return is_demo_production_chunk(chunk) or not production_exclusion_reasons(case)


def adapt_case(
    score: float,
    chunk: dict,
    case: dict,
    candidate_data: bool,
    match_evidence: dict,
) -> dict:
    metadata = chunk.get("metadata") or {}
    channel = case.get("ad_channel") or metadata.get("ad_channel")
    score_type = match_evidence.get("score_type", "bm25")
    retrieval_method = match_evidence.get(
        "retrieval_method",
        "fielded_bm25_v2",
    )
    semantic_similarity = match_evidence.get("semantic_similarity")
    public_match_evidence = {
        key: value
        for key, value in match_evidence.items()
        if key not in {"score_type", "retrieval_method"}
    }
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
        "legal_basis_details": case.get("legal_basis_details") or [],
        "legal_basis_provenance": case.get("legal_basis_provenance") or None,
        "mapped_rule_ids": normalize_string_list(case.get("mapped_rule_ids")),
        "possible_liability_rule_ids": normalize_string_list(
            case.get("possible_liability_rule_ids")
        ),
        "regulatory_logic": case.get("regulatory_logic") or None,
        "score": round(score, 6),
        "score_type": score_type,
        "retrieval_method": retrieval_method,
        "match_evidence": public_match_evidence,
        "similarity": semantic_similarity,
        "source_name": case.get("source_name", ""),
        "source_url": case.get("source_url"),
        "raw_text_path": case.get("raw_text_path", ""),
        "review_status": review_status(case),
        "source_verification_status": case.get("source_verification_status", ""),
        "approved_for_rag": approved_for_rag(case) or is_demo_production_chunk(chunk),
        "owner_approved": bool((case.get("owner_approval") or {}).get("approved") is True),
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
    return requested_group in case_groups or "general" in case_groups


def product_category_groups(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    normalized = value.strip().lower()
    if not normalized:
        return set()
    mappings = [
        ("ordinary_food", ("普通食品", "固体饮料")),
        ("health_food", ("保健食品", "保健品")),
        ("medical_device", ("医疗器械",)),
        ("medicine", ("处方药", "非处方药", "药品")),
        ("medical_service", ("医疗服务", "医院", "诊疗")),
        ("cosmetic", ("化妆品", "美妆", "美容")),
        ("real_estate", ("房地产", "房产")),
        ("game", ("游戏",)),
    ]
    return {
        group
        for group, terms in mappings
        if any(term in normalized for term in terms)
    }


def case_matches_product_category(
    request_category: str | None,
    case: dict,
    chunk: dict,
) -> bool:
    requested_groups = product_category_groups(request_category)
    if not requested_groups:
        return True
    metadata = chunk.get("metadata") or {}
    case_groups: set[str] = set()
    for value in (
            case.get("industry"),
            case.get("product_or_service"),
            metadata.get("industry"),
            metadata.get("product_or_service"),
    ):
        case_groups.update(product_category_groups(value))
    return not case_groups or bool(requested_groups & case_groups)


def normalized_channel_terms(value: Any) -> set[str]:
    if isinstance(value, list):
        text = " ".join(str(item) for item in value)
    elif isinstance(value, str):
        text = value
    else:
        return set()
    mappings = {
        "直播": ("直播", "抖音", "快手"),
        "微信": ("微信", "公众号", "朋友圈"),
        "小红书": ("小红书",),
        "互联网": ("互联网", "网页", "网站", "电商"),
        "健康科普": ("健康科普", "科普"),
        "包装": ("包装", "标签"),
        "线下": ("线下", "展板", "门店"),
    }
    normalized = set()
    for group, terms in mappings.items():
        if any(term in text for term in terms):
            normalized.add(group)
    return normalized


def case_matches_channel(
    requested_channels: list[str],
    case: dict,
    chunk: dict,
) -> bool:
    requested = normalized_channel_terms(requested_channels)
    if not requested:
        return True
    metadata = chunk.get("metadata") or {}
    known = normalized_channel_terms(
        case.get("ad_channel") or metadata.get("ad_channel")
    )
    # Missing channel metadata is not evidence of a mismatch. Known,
    # contradictory channels are filtered before ranking. A generic internet
    # label remains compatible with a specific digital platform.
    if not known or requested & known:
        return True
    digital_channels = {"直播", "微信", "小红书", "互联网", "健康科普"}
    return "互联网" in known and bool(requested & digital_channels)


def case_matches_risk_dimensions(
    requested_dimensions: list[str],
    case: dict,
    chunk: dict,
) -> bool:
    requested = {item.strip() for item in requested_dimensions if item.strip()}
    if not requested:
        return True
    metadata = chunk.get("metadata") or {}
    known = set(
        normalize_string_list(
            case.get("risk_dimensions") or chunk.get("risk_dimensions")
        )
    )
    known.update(normalize_string_list(metadata.get("risk_dimensions")))
    return bool(requested & known)


def case_matches_rule_ids(
    requested_rule_ids: list[str],
    case: dict,
    chunk: dict,
) -> bool:
    requested = {item.strip() for item in requested_rule_ids if item.strip()}
    if not requested:
        return True
    metadata = chunk.get("metadata") or {}
    known = set(
        normalize_string_list(
            case.get("mapped_rule_ids") or chunk.get("mapped_rule_ids")
        )
    )
    known.update(normalize_string_list(metadata.get("mapped_rule_ids")))
    # Legacy and candidate records may not yet be mapped. They can still be
    # constrained by risk dimensions, while mapped production records use the
    # rule ID as a hard precision filter.
    return not known or bool(requested & known)


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
    match_evidence: dict,
) -> dict:
    metadata = chunk.get("metadata") or {}
    return {
        "case_id": case["case_id"],
        "title": case.get("title", ""),
        "summary": search_case_summary(case, chunk),
        "penalty_result": case.get("penalty_result") or "",
        "source": case.get("source_name", ""),
        "similarity": (
            match_evidence.get("semantic_similarity")
            if match_evidence.get("semantic_similarity") is not None
            else round(lexical_cosine(query, str(chunk.get("text", ""))), 4)
        ),
        "source_url": case.get("source_url"),
        "legal_basis": normalize_string_list(case.get("legal_basis")),
        "legal_basis_details": case.get("legal_basis_details") or [],
        "mapped_rule_ids": normalize_string_list(case.get("mapped_rule_ids")),
        "possible_liability_rule_ids": normalize_string_list(
            case.get("possible_liability_rule_ids")
        ),
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
        min_query_coverage: float = DEFAULT_MIN_QUERY_COVERAGE,
        retrieval_mode: str = "lexical",
        min_semantic_score: float = DEFAULT_MIN_SEMANTIC_SCORE,
        semantic_index: SemanticIndex | None = None,
    ):
        if scope not in SUPPORTED_INDEX_SCOPES:
            raise ValueError("CASE_ENGINE_INDEX_SCOPE 只能是 production 或 candidate")
        if not 0 <= min_relative_score <= 1:
            raise ValueError("CASE_ENGINE_MIN_RELATIVE_SCORE 必须在 0—1 之间")
        if not 0 <= min_query_coverage <= 1:
            raise ValueError("CASE_ENGINE_MIN_QUERY_COVERAGE 必须在 0—1 之间")
        if retrieval_mode not in SUPPORTED_RETRIEVAL_MODES:
            raise ValueError(
                "CASE_ENGINE_RETRIEVAL_MODE 必须是 lexical、semantic 或 hybrid"
            )
        if not -1 <= min_semantic_score <= 1:
            raise ValueError("CASE_ENGINE_MIN_SEMANTIC_SCORE 必须在 -1—1 之间")
        self.scope = scope
        self.candidate_data = scope == "candidate"
        self.min_relative_score = min_relative_score
        self.min_query_coverage = min_query_coverage
        self.requested_retrieval_mode = retrieval_mode
        self.effective_retrieval_mode = "lexical"
        self.min_semantic_score = min_semantic_score
        self.semantic_index = semantic_index
        self.semantic_status = "disabled"
        self.load_error = ""
        self.loaded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.index_version = ""
        try:
            self.chunks = load_chunks(data_dir, scope)
            self.cases = load_cases(
                data_dir,
                scope,
                {
                    str(chunk.get("case_id"))
                    for chunk in self.chunks
                    if chunk.get("case_id")
                },
            )
            self.index_version = index_version(scope, self.chunks, self.cases)
            if retrieval_mode in {"semantic", "hybrid"}:
                semantic_path = semantic_index_path(data_dir, scope)
                if self.semantic_index is None and semantic_path.exists():
                    self.semantic_index = SemanticIndex.from_path(
                        semantic_path,
                        local_files_only=(
                            os.getenv("CASE_ENGINE_EMBEDDING_ALLOW_DOWNLOAD", "0")
                            != "1"
                        ),
                    )
                expected_embedding_model = os.getenv("CASE_ENGINE_EMBEDDING_MODEL", "")
                if self.semantic_index is None:
                    self.semantic_status = "missing_index"
                elif (
                    expected_embedding_model
                    and self.semantic_index.model_name
                    and self.semantic_index.model_name != expected_embedding_model
                ):
                    self.semantic_status = (
                        f"model_mismatch_index={self.semantic_index.model_name}"
                        f"_configured={expected_embedding_model}"
                    )
                    self.semantic_index = None
                elif (
                    self.semantic_index.chunk_fingerprint
                    != chunks_fingerprint(self.chunks)
                ):
                    self.semantic_status = "stale_index"
                    self.semantic_index = None
                elif set(self.semantic_index.embeddings) != {
                    str(chunk.get("chunk_id"))
                    for chunk in self.chunks
                    if chunk.get("chunk_id")
                }:
                    self.semantic_status = "incomplete_index"
                    self.semantic_index = None
                else:
                    self.semantic_status = "ready"
                    self.effective_retrieval_mode = retrieval_mode
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
        product_category: str | None = None,
        requested_channels: list[str] | None = None,
        risk_dimensions: list[str] | None = None,
        matched_rule_ids: list[str] | None = None,
    ) -> list[tuple[float, dict, dict, dict]]:
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
            if not case_matches_product_category(product_category, case, chunk):
                continue
            if not case_matches_channel(requested_channels or [], case, chunk):
                continue
            if not case_matches_risk_dimensions(risk_dimensions or [], case, chunk):
                continue
            if not case_matches_rule_ids(matched_rule_ids or [], case, chunk):
                continue
            visible_chunks.append(chunk)

        ranked_chunks = best_chunks_by_case(
            query,
            visible_chunks,
            top_k,
            self.min_relative_score,
            self.min_query_coverage,
            self.semantic_index,
            self.effective_retrieval_mode,
            self.min_semantic_score,
        )
        if (
            self.semantic_index is not None
            and self.semantic_index.load_error
            and self.effective_retrieval_mode != "lexical"
        ):
            self.semantic_status = f"model_error:{self.semantic_index.load_error}"
            self.effective_retrieval_mode = "lexical"
            ranked_chunks = best_chunks_by_case(
                query,
                visible_chunks,
                top_k,
                self.min_relative_score,
                self.min_query_coverage,
                retrieval_mode="lexical",
            )

        results = []
        for score, chunk, match_evidence in ranked_chunks:
            case = find_case(self.cases, chunk)
            if case is None:
                continue
            results.append((score, chunk, case, match_evidence))
        return results

    def retrieve(
        self,
        query: str,
        top_k: int,
        request_industry: str,
        *,
        product_category: str = "",
        requested_channels: list[str] | None = None,
        risk_dimensions: list[str] | None = None,
        matched_rule_ids: list[str] | None = None,
    ) -> list[dict]:
        return [
            adapt_case(score, chunk, case, self.candidate_data, match_evidence)
            for score, chunk, case, match_evidence in self.ranked_cases(
                query,
                top_k,
                request_industry=request_industry,
                product_category=product_category,
                requested_channels=requested_channels,
                risk_dimensions=risk_dimensions,
                matched_rule_ids=matched_rule_ids,
            )
        ]

    def search(
        self,
        query: str,
        top_k: int,
        tenant_id: str,
        request_industry: str,
        *,
        risk_dimensions: list[str] | None = None,
        matched_rule_ids: list[str] | None = None,
    ) -> list[dict]:
        return [
            adapt_search_case(
                query,
                chunk,
                case,
                self.candidate_data,
                match_evidence,
            )
            for _, chunk, case, match_evidence in self.ranked_cases(
                query,
                top_k,
                tenant_id,
                request_industry,
                risk_dimensions=risk_dimensions,
                matched_rule_ids=matched_rule_ids,
            )
        ]


def create_app(
    *,
    data_dir: Path | None = None,
    index_scope: str | None = None,
    api_key: str | None = None,
    retrieval_mode: str | None = None,
    min_semantic_score: float | None = None,
    allow_pilot_platform_rules: bool | None = None,
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
    min_query_coverage = float(
        os.getenv("CASE_ENGINE_MIN_QUERY_COVERAGE", str(DEFAULT_MIN_QUERY_COVERAGE))
    )
    resolved_retrieval_mode = (
        retrieval_mode
        if retrieval_mode is not None
        else os.getenv("CASE_ENGINE_RETRIEVAL_MODE", "lexical")
    ).strip().lower()
    resolved_min_semantic_score = (
        min_semantic_score
        if min_semantic_score is not None
        else float(
            os.getenv(
                "CASE_ENGINE_MIN_SEMANTIC_SCORE",
                str(DEFAULT_MIN_SEMANTIC_SCORE),
            )
        )
    )
    repository = CaseRepository(
        resolved_data_dir,
        resolved_scope,
        min_relative_score,
        min_query_coverage,
        resolved_retrieval_mode,
        resolved_min_semantic_score,
    )

    require_semantic = os.getenv("CASE_ENGINE_REQUIRE_SEMANTIC", "0") == "1"
    embedding_provider = os.getenv(
        "CASE_ENGINE_EMBEDDING_PROVIDER", "local"
    ).strip().lower()
    if require_semantic or (
        embedding_provider == "zhipu"
        and resolved_retrieval_mode in {"semantic", "hybrid"}
    ):
        if (
            repository.semantic_status != "ready"
            or repository.effective_retrieval_mode != resolved_retrieval_mode
        ):
            raise RuntimeError(
                "语义检索未就绪，拒绝启动："
                f"requested={resolved_retrieval_mode}, "
                f"status={repository.semantic_status}"
            )
        expected_model = os.getenv(
            "CASE_ENGINE_EMBEDDING_MODEL",
            "embedding-3" if embedding_provider == "zhipu" else "BAAI/bge-base-zh-v1.5",
        )
        expected_dimension = int(
            os.getenv(
                "CASE_ENGINE_EMBEDDING_DIMENSIONS",
                "2048" if embedding_provider == "zhipu" else "768",
            )
        )
        actual_model = (
            repository.semantic_index.model_name
            if repository.semantic_index is not None
            else None
        )
        actual_dimension = (
            repository.semantic_index.dimension
            if repository.semantic_index is not None
            else None
        )
        if actual_model != expected_model or actual_dimension != expected_dimension:
            raise RuntimeError(
                "语义索引配置不匹配，拒绝启动："
                f"provider={embedding_provider}, "
                f"expected_model={expected_model}, actual_model={actual_model}, "
                f"expected_dimension={expected_dimension}, "
                f"actual_dimension={actual_dimension}"
            )
    platform_rule_repository = PlatformRuleRepository(
        resolved_data_dir
        / "rules"
        / "platform"
        / "xiaohongshu_juguang_pilot.json",
        allow_pilot_rules=(
            allow_pilot_platform_rules
            if allow_pilot_platform_rules is not None
            else os.getenv("PLATFORM_RULES_ALLOW_PILOT", "0") == "1"
        ),
    )

    application = FastAPI(title="Ads Penalty Case Retrieval API", version="1.0.0")
    application.state.api_key = resolved_key
    application.state.repository = repository
    application.state.platform_rule_repository = platform_rule_repository

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
        semantic_check = (
            "disabled"
            if repository.requested_retrieval_mode == "lexical"
            else (
                "ok"
                if repository.semantic_status == "ready"
                and repository.effective_retrieval_mode
                == repository.requested_retrieval_mode
                else "degraded"
            )
        )
        return {
            "status": "ok" if key_configured and index_ready else "degraded",
            "service": "adsure-rag",
            "audit_contract": {
                "endpoint": "/audit",
                "response_schema": "audit_response_v0.2",
                "request_formats": ["normalized_json", "base_v4_fields"],
                "human_review_required": True,
            },
            "index_scope": repository.scope,
            "candidate_data": repository.candidate_data,
            "case_count": len({chunk.get("case_id") for chunk in repository.chunks}),
            "chunk_count": len(repository.chunks),
            "index_version": repository.index_version or None,
            "loaded_at": repository.loaded_at,
            "retrieval": {
                "requested_mode": repository.requested_retrieval_mode,
                "effective_mode": repository.effective_retrieval_mode,
                "semantic_status": repository.semantic_status,
                "semantic_model": (
                    repository.semantic_index.model_name
                    if repository.semantic_index is not None
                    else None
                ),
            },
            "platform_rules": {
                "platform": "小红书",
                "scene": "聚光",
                "catalog_status": (
                    platform_rule_repository.catalog.get("catalog_status")
                    or "unavailable"
                ),
                "production_ready": platform_rule_repository.production_ready,
                "pilot_enabled": platform_rule_repository.allow_pilot_rules,
                "loaded_rule_count": len(platform_rule_repository.rules),
                "policy_snapshot_id": (
                    platform_rule_repository.snapshot_id or None
                ),
                "load_error": platform_rule_repository.load_error or None,
            },
            "checks": {
                "index": "ok" if index_ready else "error",
                "api_key": "configured" if key_configured else "missing",
                "semantic": semantic_check,
                "platform_rules": (
                    "ok"
                    if platform_rule_repository.production_ready
                    else "not_production_ready"
                ),
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
                product_category=validated["product_category"],
                requested_channels=list(
                    dict.fromkeys(
                        validated["platform"]
                        + ([validated["ad_channel"]] if validated["ad_channel"] else [])
                    )
                ),
                risk_dimensions=validated["risk_dimensions"],
                matched_rule_ids=validated["matched_rule_ids"],
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
                    "retrieval_method": (
                        cases[0]["retrieval_method"]
                        if cases
                        else (
                            "hybrid_rrf_v1"
                            if repository.effective_retrieval_mode == "hybrid"
                            else (
                                "dense_semantic_v1"
                                if repository.effective_retrieval_mode == "semantic"
                                else "fielded_bm25_v2"
                            )
                        )
                    ),
                    "requested_retrieval_mode": repository.requested_retrieval_mode,
                    "effective_retrieval_mode": repository.effective_retrieval_mode,
                    "semantic_status": repository.semantic_status,
                    "min_query_coverage": repository.min_query_coverage,
                },
            },
        }

    @application.post("/audit", response_model=None)
    def audit_material(
        request: Request,
        payload: Any = Body(...),
        x_api_key: str | None = Header(default=None),
    ):
        if not application.state.api_key:
            return error_response("服务端未配置 ADSURE_API_KEY", 503)
        if not x_api_key or not hmac.compare_digest(x_api_key, application.state.api_key):
            return error_response("API Key 无效或缺失", 401)
        validated, message = normalize_audit_request(payload, max_content_length)
        if message:
            return error_response(message)
        try:
            return {"code": 0, "msg": "ok", "data": build_audit_response(validated)}
        except Exception:
            LOGGER.exception("audit_failed request_id=%s", request.state.request_id)
            return error_response("审核引擎暂不可用", 503)

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
                risk_dimensions=[
                    rule["dimension"]
                    for rule in validated["matched_rules"]
                    if rule["dimension"]
                ],
                matched_rule_ids=[
                    rule["rule_id"]
                    for rule in validated["matched_rules"]
                    if rule["rule_id"]
                ],
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
                    "similarity_method": (
                        "semantic_cosine"
                        if repository.effective_retrieval_mode == "semantic"
                        else (
                            "semantic_cosine_when_available_else_lexical_cosine"
                            if repository.effective_retrieval_mode == "hybrid"
                            else "lexical_cosine_v1"
                        )
                    ),
                    "retrieval_method": (
                        "hybrid_rrf_v1"
                        if repository.effective_retrieval_mode == "hybrid"
                        else (
                            "dense_semantic_v1"
                            if repository.effective_retrieval_mode == "semantic"
                            else "fielded_bm25_v2"
                        )
                    ),
                    "requested_retrieval_mode": repository.requested_retrieval_mode,
                    "effective_retrieval_mode": repository.effective_retrieval_mode,
                    "semantic_status": repository.semantic_status,
                },
            },
        }

    @application.post("/platform-rules/precheck", response_model=None)
    def platform_rules_precheck(
        payload: Any = Body(...),
        x_api_key: str | None = Header(default=None),
    ):
        if not application.state.api_key:
            return error_response("服务端未配置 ADSURE_API_KEY", 503)
        if not x_api_key or not hmac.compare_digest(
            x_api_key,
            application.state.api_key,
        ):
            return error_response("API Key 无效或缺失", 401)

        result, message = platform_rule_repository.precheck(payload)
        if message:
            return error_response(message)
        return {"code": 0, "msg": "ok", "data": result}

    return application


_APP: FastAPI | None = None


def eager_app() -> FastAPI:
    """按需构建 ASGI 应用（供 ``uvicorn src.api:app`` 使用）。

    语义检索未就绪时 :func:`create_app` 会抛 ``RuntimeError``，生产启动因此
    被拦住。这里用 PEP 562 的模块级 ``__getattr__`` 延迟到真正取 ``app`` 时才
    构建，预检 / 评测脚本 import 本模块读取 ``CaseRepository`` 时不会被启动闸门
    打断，从而仍能打印完整的案例数与切片数报告。
    """
    global _APP
    if _APP is None:
        _APP = create_app()
    return _APP


def __getattr__(name: str):
    if name == "app":
        return eager_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
