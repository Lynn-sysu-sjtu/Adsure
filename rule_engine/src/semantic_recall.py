# -*- coding: utf-8 -*-
"""Semantic recall for MVP.

Default mode uses local character n-gram similarity so tests and demos do not
depend on external services. Set ADSURE_SEMANTIC_BACKEND=zhipu or pass
backend="embedding" to use a real embedding client.
"""

import math
import os
import re
from pathlib import Path

from rule_vector_index import DEFAULT_VECTOR_INDEX_PATH, load_rule_vector_index, vector_text_hash


def _normalize(text):
    return re.sub(r"\s+", "", str(text or "").lower())


def _char_ngrams(text, n=2):
    text = _normalize(text)
    if not text:
        return set()
    if len(text) <= n:
        return {text}
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _jaccard(left_items, right_items):
    if not left_items or not right_items:
        return 0.0
    return len(left_items & right_items) / len(left_items | right_items)


def similarity(left, right):
    left_bigram = _char_ngrams(left, n=2)
    right_bigram = _char_ngrams(right, n=2)
    left_unigram = _char_ngrams(left, n=1)
    right_unigram = _char_ngrams(right, n=1)
    bigram_score = _jaccard(left_bigram, right_bigram)
    unigram_score = _jaccard(left_unigram, right_unigram)
    return max(bigram_score, unigram_score * 0.55)


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(item) * float(item) for item in left))
    right_norm = math.sqrt(sum(float(item) * float(item) for item in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _semantic_query(request, context_package):
    material = request.get("material", {})
    context = request.get("context", {})
    parts = [
        material.get("content", ""),
        material.get("supplemental_background", ""),
        context_package.get("context_summary", ""),
        context.get("industry", ""),
        context.get("product_category", ""),
        context.get("scenario", ""),
        " ".join(context.get("platforms", [])),
        " ".join(context.get("core_claims", [])),
    ]
    return " ".join(str(part) for part in parts if part)


def _as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


WILDCARD_SCOPE_VALUES = {"通用", "全部", "不限"}


def _has_scope_match(request_values, allowed_values):
    allowed = [str(item) for item in _as_list(allowed_values)]
    if not allowed or set(allowed) & WILDCARD_SCOPE_VALUES:
        return True
    values = [str(item) for item in _as_list(request_values)]
    if not values:
        return True
    return bool(set(values) & set(allowed))


def _negative_signal_hits(rule, query):
    keyword_signals = (rule.get("detection", {}) or {}).get("keyword_signals", {}) or {}
    negative_terms = keyword_signals.get("negative_signals", []) or []
    return [term for term in negative_terms if term and str(term) in query]


def _rule_filter_reasons(rule, request, query=""):
    context = request.get("context", {})
    applies_to = rule.get("applies_to", {}) or {}
    reasons = []

    if not _has_scope_match(context.get("industry"), applies_to.get("industries") or [rule.get("industry")]):
        reasons.append("industry_scope_mismatch")
    if not _has_scope_match(context.get("material_type"), applies_to.get("material_types")):
        reasons.append("material_type_scope_mismatch")
    if not _has_scope_match(context.get("product_category"), applies_to.get("product_categories")):
        reasons.append("product_category_scope_mismatch")
    if not _has_scope_match(context.get("channels") or context.get("channel"), applies_to.get("channels")):
        reasons.append("channel_scope_mismatch")

    preconditions = rule.get("preconditions", {}) or {}
    for field_name in preconditions.get("required_context_fields", []) or []:
        if field_name == "content":
            if not request.get("material", {}).get("content"):
                reasons.append("missing_required_context:content")
        elif not context.get(field_name) and not request.get("material", {}).get(field_name):
            reasons.append(f"missing_required_context:{field_name}")

    negative_hits = _negative_signal_hits(rule, query) if query else []
    if negative_hits:
        reasons.append("negative_signal_hit:" + ",".join(str(item) for item in negative_hits))
    return reasons


def _rule_applies_to_context(rule, request, query=""):
    return not _rule_filter_reasons(rule, request, query=query)

def _embedding_scores(query, candidate_texts, embedding_client):
    vectors = embedding_client.embed_texts([query] + candidate_texts)
    query_vector = vectors[0]
    return [cosine_similarity(query_vector, vector) for vector in vectors[1:]]


def _vector_index_path(path=None):
    if path:
        return Path(path)
    env_path = os.getenv("ADSURE_RULE_VECTOR_INDEX")
    if env_path:
        return Path(env_path)
    return DEFAULT_VECTOR_INDEX_PATH


def _semantic_threshold(use_embedding, threshold):
    if threshold is not None:
        return float(threshold)
    env_threshold = os.getenv("ADSURE_SEMANTIC_THRESHOLD")
    if env_threshold not in (None, ""):
        try:
            return float(env_threshold)
        except ValueError:
            pass
    return 0.72 if use_embedding else 0.06


def _cached_embedding_candidates(applicable, vector_index_path):
    index = load_rule_vector_index(vector_index_path)
    cached = []
    for rule, vector_text in applicable:
        key = (rule.get("rule_id"), vector_text_hash(vector_text))
        entry = index.get(key)
        if entry:
            cached.append((rule, entry.get("embedding")))
    return cached


def semantic_recall_rules(
    rules,
    request,
    context_package,
    threshold=None,
    limit=5,
    backend=None,
    embedding_client=None,
    vector_index_path=None,
):
    query = _semantic_query(request, context_package)
    backend = (backend or os.getenv("ADSURE_SEMANTIC_BACKEND") or "local").lower()
    use_embedding = backend in {"embedding", "zhipu", "zhipu_embedding"}
    threshold = _semantic_threshold(use_embedding, threshold)

    applicable = []
    for rule in rules:
        if not _rule_applies_to_context(rule, request, query=query):
            continue
        recall = rule.get("recall", {}) or {}
        if not recall.get("semantic_enabled"):
            continue
        vector_text = recall.get("vector_text") or ""
        if not vector_text:
            continue
        applicable.append((rule, vector_text))

    if use_embedding and applicable:
        if embedding_client is None:
            from zhipu_embedding_client import ZhipuEmbeddingClient

            embedding_client = ZhipuEmbeddingClient()

        cached = _cached_embedding_candidates(applicable, _vector_index_path(vector_index_path))
        candidates = []
        if cached:
            query_vector = embedding_client.embed_texts([query])[0]
            for rule, rule_vector in cached:
                score = cosine_similarity(query_vector, rule_vector)
                if score < threshold:
                    continue
                candidates.append((rule, [f"semantic_embedding_cached:{score:.3f}"]))
        else:
            scores = _embedding_scores(query, [text for _, text in applicable], embedding_client)
            for (rule, _), score in zip(applicable, scores):
                if score < threshold:
                    continue
                candidates.append((rule, [f"semantic_embedding:{score:.3f}"]))
    else:
        candidates = []
        for rule, vector_text in applicable:
            score = similarity(query, vector_text)
            if score < threshold:
                continue
            candidates.append((rule, [f"semantic:{score:.3f}"]))

    candidates.sort(key=lambda item: (-float(item[1][0].split(":")[1]), (item[0].get("serial_no") or 999999)))
    return candidates[:limit]

def semantic_recall_diagnostics(
    rules,
    request,
    context_package,
    threshold=None,
    backend=None,
    embedding_client=None,
    vector_index_path=None,
    top_k=10,
):
    """Return semantic recall diagnostics without changing recall behavior."""
    query = _semantic_query(request, context_package)
    backend = (backend or os.getenv("ADSURE_SEMANTIC_BACKEND") or "local").lower()
    use_embedding = backend in {"embedding", "zhipu", "zhipu_embedding"}
    threshold = _semantic_threshold(use_embedding, threshold)

    applicable = []
    rejected = []
    for rule in rules:
        recall = rule.get("recall", {}) or {}
        reasons = []
        if not recall.get("semantic_enabled"):
            reasons.append("semantic_disabled")
        vector_text = recall.get("vector_text") or ""
        if not vector_text:
            reasons.append("missing_vector_text")
        reasons.extend(_rule_filter_reasons(rule, request, query=query))
        if reasons:
            rejected.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "title": rule.get("title"),
                    "reasons": reasons,
                }
            )
            continue
        applicable.append((rule, vector_text))

    scored = []
    if use_embedding and applicable:
        if embedding_client is None:
            from zhipu_embedding_client import ZhipuEmbeddingClient

            embedding_client = ZhipuEmbeddingClient()
        index_path = _vector_index_path(vector_index_path)
        index = load_rule_vector_index(index_path)
        cached_items = []
        missing_cache = []
        for rule, vector_text in applicable:
            key = (rule.get("rule_id"), vector_text_hash(vector_text))
            entry = index.get(key)
            if entry and entry.get("embedding"):
                cached_items.append((rule, vector_text, entry.get("embedding")))
            else:
                missing_cache.append((rule, vector_text))
        if cached_items:
            query_vector = embedding_client.embed_texts([query])[0]
            for rule, vector_text, rule_vector in cached_items:
                score = cosine_similarity(query_vector, rule_vector)
                scored.append((rule, vector_text, score, "semantic_embedding_cached"))
            for rule, _ in missing_cache:
                rejected.append(
                    {
                        "rule_id": rule.get("rule_id"),
                        "title": rule.get("title"),
                        "reasons": ["missing_cached_vector"],
                    }
                )
        else:
            scores = _embedding_scores(query, [text for _, text in applicable], embedding_client)
            for (rule, vector_text), score in zip(applicable, scores):
                scored.append((rule, vector_text, score, "semantic_embedding"))
    else:
        for rule, vector_text in applicable:
            scored.append((rule, vector_text, similarity(query, vector_text), "semantic"))

    scored.sort(key=lambda item: (-float(item[2]), (item[0].get("serial_no") or 999999)))
    top_candidates = []
    for rank, (rule, vector_text, score, source) in enumerate(scored[:top_k], start=1):
        recall = rule.get("recall", {}) or {}
        top_candidates.append(
            {
                "rank": rank,
                "rule_id": rule.get("rule_id"),
                "serial_no": rule.get("serial_no"),
                "title": rule.get("title"),
                "dimension": rule.get("dimension"),
                "risk_level": rule.get("risk_level"),
                "trigger_layer": recall.get("trigger_layer") or "content",
                "semantic_role": recall.get("semantic_role") or "fallback",
                "score": round(float(score), 6),
                "passed_threshold": score >= threshold,
                "score_source": source,
                "vector_text": vector_text,
            }
        )
    return {
        "backend": backend,
        "threshold": threshold,
        "query": query,
        "applicable_count": len(applicable),
        "rejected_count": len(rejected),
        "top_candidates": top_candidates,
        "rejected_rules": rejected,
    }

