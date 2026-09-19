import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


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
    "产品",
    "商品",
    "宣传",
    "发布",
    "公司",
    "经营",
}

FIELD_WEIGHTS = {
    "illegal_claims": 4.0,
    "risk_dimensions": 3.0,
    "mapped_rule_ids": 3.0,
    "product_or_service": 2.0,
    "keywords": 2.0,
    "regulatory_logic": 1.5,
    "vector_text": 1.0,
    "text": 1.0,
}


@dataclass(frozen=True)
class ScoredChunk:
    score: float
    chunk: dict
    matched_terms: list[str]
    query_coverage: float
    matched_fields: list[str]


def unique_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def tokenize(text: str) -> list[str]:
    """Tokenize Chinese as bi/tri-grams and keep complete alphanumeric terms.

    Single Chinese characters create excessive accidental overlap in short ad
    copy. Bi/tri-grams preserve exact-phrase recall without requiring a runtime
    dictionary or external segmentation service.
    """

    normalized = str(text or "").lower()
    tokens = re.findall(r"[a-z0-9_:-]+", normalized)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(sequence) == 1:
            continue
        for size in (2, 3):
            if len(sequence) < size:
                continue
            tokens.extend(
                sequence[index : index + size]
                for index in range(len(sequence) - size + 1)
            )
    return tokens


def informative_terms(text: str) -> list[str]:
    return unique_list(
        [
            token
            for token in tokenize(text)
            if token not in GENERIC_RETRIEVAL_TOKENS
        ]
    )


def normalize_field_value(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item)
    if value is None:
        return ""
    return str(value)


def search_fields(chunk: dict) -> dict[str, str]:
    fields = chunk.get("search_fields")
    if isinstance(fields, dict):
        normalized = {
            str(name): normalize_field_value(value)
            for name, value in fields.items()
            if normalize_field_value(value)
        }
    else:
        normalized = {}
    normalized.setdefault("text", str(chunk.get("text", "")))
    if chunk.get("risk_dimensions"):
        normalized.setdefault(
            "risk_dimensions",
            normalize_field_value(chunk.get("risk_dimensions")),
        )
    if chunk.get("keywords"):
        normalized.setdefault("keywords", normalize_field_value(chunk.get("keywords")))
    return normalized


def weighted_document(chunk: dict) -> tuple[Counter[str], float, dict[str, set[str]]]:
    counts: Counter[str] = Counter()
    field_terms: dict[str, set[str]] = {}
    weighted_length = 0.0
    for field_name, text in search_fields(chunk).items():
        tokens = tokenize(text)
        if not tokens:
            continue
        weight = FIELD_WEIGHTS.get(field_name, 1.0)
        field_terms[field_name] = set(tokens)
        for token, count in Counter(tokens).items():
            counts[token] += count * weight
        weighted_length += len(tokens) * weight
    return counts, weighted_length, field_terms


def fielded_bm25_scores(query: str, chunks: list[dict]) -> list[ScoredChunk]:
    if not chunks:
        return []

    query_terms = informative_terms(query)
    if not query_terms:
        return []

    documents = [weighted_document(chunk) for chunk in chunks]
    document_frequency: Counter[str] = Counter()
    for counts, _length, _fields in documents:
        document_frequency.update(set(counts))
    average_length = (
        sum(length for _counts, length, _fields in documents) / len(documents)
    )

    total_documents = len(chunks)
    k1 = 1.5
    b = 0.75
    scored: list[ScoredChunk] = []
    for chunk, (term_frequency, document_length, field_terms) in zip(chunks, documents):
        score = 0.0
        matched_terms = [term for term in query_terms if term in term_frequency]
        for term in matched_terms:
            tf = term_frequency[term]
            df = document_frequency[term]
            inverse_document_frequency = math.log(
                1 + (total_documents - df + 0.5) / (df + 0.5)
            )
            denominator = tf + k1 * (
                1 - b + b * document_length / (average_length or 1)
            )
            score += inverse_document_frequency * tf * (k1 + 1) / denominator

        matched_fields = [
            field_name
            for field_name, terms in field_terms.items()
            if any(term in terms for term in matched_terms)
        ]
        scored.append(
            ScoredChunk(
                score=score,
                chunk=chunk,
                matched_terms=matched_terms,
                query_coverage=len(matched_terms) / len(query_terms),
                matched_fields=matched_fields,
            )
        )
    return sorted(scored, key=lambda item: item.score, reverse=True)


def bm25_scores(query: str, chunks: list[dict]) -> list[tuple[float, dict]]:
    """Compatibility adapter for CLI callers that consume score/chunk tuples."""

    return [(item.score, item.chunk) for item in fielded_bm25_scores(query, chunks)]
