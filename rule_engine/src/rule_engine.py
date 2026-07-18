# -*- coding: utf-8 -*-
"""MVP rule engine flow for Feishu-triggered ad compliance audits."""

import os
import re
from datetime import datetime
from pathlib import Path

from field_mapper import map_feishu_payload
from kg_rule_store import load_rule_library
from llm_judgment import judge_with_llm, judge_with_mock_llm
from semantic_recall import semantic_recall_rules


STANDARD_MODE_REASON = "MVP阶段统一使用标准审核模式，极速和深度模式仅预留接口。"


class AuditInputError(ValueError):
    """Raised when a Feishu audit payload lacks required input."""


def _joined_context(request):
    material = request.get("material", {})
    context = request.get("context", {})
    parts = [
        material.get("content", ""),
        material.get("supplemental_background", ""),
        context.get("industry", ""),
        context.get("material_type", ""),
        context.get("product_category", ""),
        context.get("product_filing_name", ""),
        context.get("approval_or_filing_number", ""),
        context.get("scenario", ""),
        context.get("game_name", ""),
        context.get("ip_name", ""),
        " ".join(context.get("platforms", [])),
        " ".join(context.get("core_claims", [])),
    ]
    return " ".join(str(part) for part in parts if part)


def _keyword_text(request):
    return str((request.get("material", {}) or {}).get("content", "") or "")


def validate_request(request):
    if not request.get("material", {}).get("content"):
        raise AuditInputError("缺少必填字段：①运营·物料内容")
    if not request.get("context", {}).get("industry"):
        raise AuditInputError("缺少必填字段：①运营·行业领域")


def build_context_package(request):
    material = request.get("material", {})
    context = request.get("context", {})
    claims = "、".join(context.get("core_claims", [])) or "未填写核心宣称"
    platforms = "、".join(context.get("platforms", [])) or "未填写投放平台"
    summary = (
        f"该物料属于{context.get('industry') or '未知行业'}，"
        f"物料类型为{context.get('material_type') or '未知'}，"
        f"投放平台为{platforms}，核心宣称为{claims}。"
    )
    return {
        "material_text": material.get("content", ""),
        "industry": context.get("industry", ""),
        "material_type": context.get("material_type", ""),
        "platforms": context.get("platforms", []),
        "product_category": context.get("product_category", ""),
        "core_claims": context.get("core_claims", []),
        "scenario": context.get("scenario", ""),
        "context_summary": summary,
        "missing_facts": [
            label
            for label, value in [
                ("投放平台", context.get("platforms")),
                ("核心宣称功效", context.get("core_claims")),
                ("产品备案名称", context.get("product_filing_name")),
            ]
            if not value
        ],
    }


def _rule_applies_to_context(rule, request):
    context = request.get("context", {})
    industry = context.get("industry")
    applies_to = rule.get("applies_to", {}) or {}
    industries = applies_to.get("industries") or [rule.get("industry")]
    if industry and industries and "通用" not in industries and industry not in industries:
        return False
    return True



SEMANTIC_RECALL_CUES = [
    "??", "??", "??", "??", "??", "??", "??", "??", "??",
    "??", "??", "??", "??", "??", "??", "??", "??",
    "??", "??", "??", "??", "??", "??", "??", "?", "??",
    "??", "??", "??", "??", "??", "??", "???", "??",
    "??", "??", "??", "??", "??", "??", "??", "??",
    "??", "??", "??", "???", "???", "??",
    "link", "shopping", "continue", "gift", "reward", "free", "claim",
    "certified", "patent", "official", "best", "first",
]


def _has_semantic_recall_cue(request):
    material = request.get("material", {}) or {}
    text = " ".join(
        str(part or "")
        for part in [material.get("content", ""), material.get("supplemental_background", "")]
    ).lower()
    return any(str(cue).lower() in text for cue in SEMANTIC_RECALL_CUES)

def _rule_trigger_layer(rule):
    return (rule.get("recall", {}) or {}).get("trigger_layer") or "content"


def _is_content_trigger_rule(rule):
    return _rule_trigger_layer(rule) == "content"


def _rule_sort_no(rule):
    return rule.get("serial_no") or 999999


def _keyword_priority(rule):
    value = (rule.get("recall", {}) or {}).get("keyword_priority", 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
def _keyword_hits(rule, text):
    keyword_signals = (rule.get("detection", {}) or {}).get("keyword_signals", {}) or {}
    hits = []
    for term in keyword_signals.get("hit_terms", []):
        if term and term in text:
            hits.append(term)
    for pattern in keyword_signals.get("regex", []):
        try:
            if re.search(pattern, text):
                hits.append(f"regex:{pattern}")
        except re.error:
            continue
    return hits



def _fallback_supplement_threshold():
    env_threshold = os.getenv("ADSURE_FALLBACK_SEMANTIC_THRESHOLD")
    if env_threshold not in (None, ""):
        try:
            return float(env_threshold)
        except ValueError:
            pass
    backend = (os.getenv("ADSURE_SEMANTIC_BACKEND") or "local").lower()
    return 0.82 if backend in {"embedding", "zhipu", "zhipu_embedding"} else 0.10

def _no_keyword_semantic_threshold():
    env_threshold = os.getenv("ADSURE_NO_KEYWORD_SEMANTIC_THRESHOLD")
    if env_threshold not in (None, ""):
        try:
            return float(env_threshold)
        except ValueError:
            pass
    backend = (os.getenv("ADSURE_SEMANTIC_BACKEND") or "local").lower()
    return 0.58 if backend in {"embedding", "zhipu", "zhipu_embedding"} else 0.70

def recall_rules(
    rules,
    request,
    context_package=None,
    keyword_limit=8,
    semantic_limit=5,
    fallback_supplement_threshold=None,
    fallback_supplement_limit=2,
):
    text = _keyword_text(request)
    content_rules = [rule for rule in rules if _is_content_trigger_rule(rule)]
    recalled = []
    for rule in content_rules:
        if not _rule_applies_to_context(rule, request):
            continue
        hits = _keyword_hits(rule, text)
        if not hits:
            continue
        recalled.append((rule, hits))

    recalled.sort(
        key=lambda item: (
            _keyword_priority(item[0]) * -1,
            item[0].get("risk_level") != "高",
            len(item[1]) * -1,
            _rule_sort_no(item[0]),
        )
    )
    keyword_recalled = recalled[:keyword_limit]
    if not context_package:
        return keyword_recalled

    seen_ids = {rule.get("rule_id") for rule, _ in keyword_recalled}
    semantic_recalled = []

    def add_semantic_candidates(candidate_rules, limit, threshold=None):
        for rule, hits in semantic_recall_rules(
            candidate_rules,
            request,
            context_package,
            threshold=threshold,
            limit=limit,
        ):
            rule_id = rule.get("rule_id")
            if rule_id in seen_ids:
                continue
            seen_ids.add(rule_id)
            semantic_recalled.append((rule, hits))

    if keyword_recalled:
        primary_rules = [
            rule
            for rule in content_rules
            if (rule.get("recall", {}) or {}).get("semantic_role") == "primary"
        ]
        if primary_rules:
            add_semantic_candidates(primary_rules, semantic_limit)

        fallback_rules = [
            rule
            for rule in content_rules
            if (rule.get("recall", {}) or {}).get("semantic_role", "fallback") == "fallback"
        ]
        if fallback_rules and fallback_supplement_limit > 0:
            threshold = fallback_supplement_threshold
            if threshold is None:
                threshold = _fallback_supplement_threshold()
            add_semantic_candidates(fallback_rules, fallback_supplement_limit, threshold=threshold)
        return keyword_recalled + semantic_recalled

    threshold = None if _has_semantic_recall_cue(request) else _no_keyword_semantic_threshold()
    add_semantic_candidates(content_rules, semantic_limit, threshold=threshold)
    return keyword_recalled + semantic_recalled


FACT_CLAIM_TERMS = [
    "\u4e13\u5229", "\u4e13\u5229\u6280\u672f", "\u5907\u6848", "\u5907\u6848\u53f7", "\u6279\u51c6\u6587\u53f7", "\u84dd\u5e3d\u5b50",
    "\u8ba4\u8bc1", "\u5b98\u65b9\u8ba4\u8bc1", "\u6743\u5a01\u8ba4\u8bc1", "\u56fd\u5bb6\u8ba4\u8bc1", "\u8d44\u8d28", "\u8bb8\u53ef\u8bc1",
    "\u68c0\u6d4b\u62a5\u544a", "\u68c0\u9a8c\u62a5\u544a", "\u8bc1\u660e", "\u8bc1\u660e\u6750\u6599", "\u9500\u91cf", "\u9500\u91cf\u7b2c\u4e00",
    "\u6392\u540d\u7b2c\u4e00", "\u7b2c\u4e00", "\u6388\u6743", "\u7248\u53f7", "\u8457\u4f5c\u6743", "\u4e13\u5229\u53f7",
    "patent", "patented", "certification", "certified", "official",
    "report", "proof", "approval", "filing", "license",
]

CONTEXT_FIELD_LABELS = {
    "content": "物料内容",
    "industry": "行业领域",
    "material_type": "物料类型",
    "platforms": "投放平台",
    "product_category": "产品品类",
    "product_filing_name": "产品备案名称",
    "approval_or_filing_number": "批准文号/备案号/资质编号",
    "core_claims": "核心宣称功效",
    "scenario": "物料涉及场景",
    "game_name": "游戏名称",
    "ip_name": "IP名称",
}

def _is_fact_trigger_rule(rule):
    return _rule_trigger_layer(rule) == "fact"


def _fact_claim_hits(text):
    lower = str(text or "").lower()
    return [term for term in FACT_CLAIM_TERMS if term.lower() in lower]


def _context_value(request, field_name):
    context = request.get("context", {}) or {}
    material = request.get("material", {}) or {}
    if field_name in context:
        return context.get(field_name)
    if field_name in material:
        return material.get(field_name)
    return None


def _is_missing_value(value):
    return value is None or value == "" or value == []


def _missing_required_context_fields(rule, request):
    missing = []
    preconditions = rule.get("preconditions", {}) or {}
    for field_name in preconditions.get("required_context_fields", []) or []:
        if field_name == "content":
            continue
        if _is_missing_value(_context_value(request, field_name)):
            missing.append(field_name)
    return missing


def _fact_rule_surface(rule):
    parts = [
        rule.get("title", ""),
        rule.get("dimension", ""),
        str(rule.get("preconditions", {}) or {}),
        str((rule.get("detection", {}) or {}).get("keyword_signals", {}) or {}),
        str(rule.get("recall", {}) or {}),
    ]
    for item in rule.get("legal_basis", []) or []:
        parts.append(str(item.get("text", "")))
    return " ".join(parts)


def fact_recall_rules(rules, request, context_package=None, limit=5):
    text = _keyword_text(request)
    claim_hits = _fact_claim_hits(text)
    recalled = []
    for rule in rules:
        if not _is_fact_trigger_rule(rule):
            continue
        if not _rule_applies_to_context(rule, request):
            continue
        keyword_hits = _keyword_hits(rule, text)
        missing_fields = _missing_required_context_fields(rule, request)
        surface = _fact_rule_surface(rule)
        surface_claim_hits = [term for term in claim_hits if term.lower() in surface.lower()]
        if not keyword_hits and not (missing_fields and surface_claim_hits):
            continue
        hits = list(keyword_hits)
        hits.extend(f"fact_claim:{term}" for term in surface_claim_hits[:3] if term not in hits)
        hits.extend(f"fact_missing_context:{field_name}" for field_name in missing_fields)
        if not hits:
            hits.append("fact_verification_required")
        recalled.append((rule, hits))

    recalled.sort(
        key=lambda item: (
            item[0].get("risk_level") != "\u9ad8",
            len(item[1]) * -1,
            _rule_sort_no(item[0]),
        )
    )
    return recalled[:limit]


def _fact_supplement_items(fact_recalled):
    items = []
    seen = set()
    for rule, hits in fact_recalled:
        missing = [str(hit).removeprefix("fact_missing_context:") for hit in hits if str(hit).startswith("fact_missing_context:")]
        if missing:
            label_text = "、".join(CONTEXT_FIELD_LABELS.get(field, field) for field in missing)
            item = f"{rule.get('title') or rule.get('rule_id')}：请补充{label_text}。"
        else:
            item = f"{rule.get('title') or rule.get('rule_id')}：请补充或核验与该事实宣称对应的证明材料。"
        if item not in seen:
            seen.add(item)
            items.append(item)
    return items


def _fact_supplement_advice(fact_recalled):
    items = _fact_supplement_items(fact_recalled)
    if not items:
        return ""
    return "该物料涉及事实/资质/证明材料核验，请运营补充或确认以下材料：" + "；".join(items)

def _legal_basis_text(rule):
    labels = []
    for lb in rule.get("legal_basis", []):
        source = lb.get("source_id", "")
        article = lb.get("article", "")
        if source or article:
            labels.append(f"{source}{article}")
    return labels


def _legal_authority_level_label(rule, legal_basis):
    level = legal_basis.get("legal_level")
    level_map = {
        "1": "法律",
        "2": "行政法规",
        "3": "部门规章",
        "4": "规范性文件/国家标准/监管指引",
    }
    if level is not None and str(level).strip():
        return level_map.get(str(level).strip(), f"效力层级{level}")
    source_type = str(legal_basis.get("source_type") or rule.get("source_type") or "").strip()
    if source_type:
        return source_type
    return "规则依据"

def _regex_hit_label(hit):
    pattern = str(hit).removeprefix("regex:")
    if any(token in pattern for token in ["见效", "改善", "逆转", "恢复", "天", "小时"]):
        return "短期见效或功效承诺类表达"
    if any(token in pattern for token in ["国家级", "最高级", "最佳", "顶级", "唯一", "第一", "首选"]):
        return "绝对化或最高级表述"
    if any(token in pattern for token in ["买", "送", "免费", "返利", "限时"]):
        return "价格促销或利益承诺类表达"
    return "规则库正则模式命中"


def _humanize_hits(hits):
    readable = []
    for hit in hits:
        text = str(hit)
        if text.startswith("semantic"):
            continue
        if text.startswith("fact_missing_context:"):
            field_name = text.removeprefix("fact_missing_context:")
            readable.append("需补充" + CONTEXT_FIELD_LABELS.get(field_name, field_name))
            continue
        if text.startswith("fact_claim:"):
            readable.append("事实宣称：" + text.removeprefix("fact_claim:"))
            continue
        if text == "fact_verification_required":
            readable.append("需进行事实核验")
            continue
        if text.startswith("regex:"):
            readable.append(_regex_hit_label(text))
        else:
            readable.append(text)
    return sorted(set(item for item in readable if item))


def _rule_display_label(rule):
    rule_id = rule.get("rule_id") or rule.get("serial_no") or "UNKNOWN"
    title = rule.get("title") or "未命名规则"
    dimension = rule.get("dimension") or ""
    risk = rule.get("risk_level") or ""
    suffix = f"（{dimension}·{risk}）" if dimension or risk else ""
    return f"[{rule_id}] {title}{suffix}"


def _precheck_hit_summary(matched_rules):
    if not matched_rules:
        return "无明显命中"
    return "命中规则：" + "；".join(_rule_display_label(rule) for rule in matched_rules[:8])


def _format_matched_rules_section(matched_rules):
    if not matched_rules:
        return ""
    lines = ["【命中规则明细】"]
    for rule in matched_rules:
        lines.append(f"- {_rule_display_label(rule)} → {rule.get('judgment') or '初步命中'}")
    return "\n".join(lines)


def _format_legal_basis_details(matched_rules):
    lines = []
    seen = set()
    for rule in matched_rules:
        for lb in rule.get("legal_basis_detail", []) or []:
            if not isinstance(lb, dict):
                continue
            text = str(lb.get("text") or "").strip()
            if not text:
                continue
            source = str(lb.get("source_id") or lb.get("source") or "").strip()
            article = str(lb.get("article") or lb.get("article_id") or "").strip()
            key = (source, article, text)
            if key in seen:
                continue
            seen.add(key)
            label = "".join(part for part in [source, article] if part) or "规则原文"
            level_label = _legal_authority_level_label(rule, lb)
            lines.append(f"- {_rule_display_label(rule)}\n  [{level_label}] {label}：{text}")
    if not lines:
        return ""
    return "【触犯法条原文】\n" + "\n".join(lines)


def _ensure_opinion_type_prefix(audit_opinion, opinion_type):
    opinion_type = opinion_type or "待判断"
    text = audit_opinion or ""
    if "意见类型" in text[:80]:
        return text
    return f"意见类型：{opinion_type}\n{text}"


def _compose_audit_opinion(fact_advice, llm_judgment, matched_rules):
    base_opinion = _ensure_opinion_type_prefix(
        llm_judgment.get("audit_opinion") or "",
        llm_judgment.get("opinion_type"),
    )
    parts = []
    if fact_advice:
        parts.append(fact_advice)
    if base_opinion:
        parts.append(base_opinion)
    matched_section = _format_matched_rules_section(matched_rules)
    if matched_section:
        parts.append(matched_section)
    legal_section = _format_legal_basis_details(matched_rules)
    if legal_section:
        parts.append(legal_section)
    return "\n\n".join(parts)


def _matched_rule(rule, hits):
    detection = rule.get("detection", {}) or {}
    if all(str(hit).startswith("semantic") for hit in hits):
        recall_channel = "semantic"
    elif any(str(hit).startswith("fact_") for hit in hits):
        recall_channel = "fact"
    else:
        recall_channel = "keyword"
    return {
        "rule_id": rule.get("rule_id"),
        "rule_uid": rule.get("rule_uid"),
        "serial_no": rule.get("serial_no"),
        "title": rule.get("title"),
        "dimension": rule.get("dimension"),
        "risk_level": rule.get("risk_level"),
        "judgment": "初步命中",
        "match_reason": "命中规则：" + (rule.get("title") or str(rule.get("rule_id") or "未命名规则")),
        "raw_hit_terms": _humanize_hits(hits),
        "recall_channel": recall_channel,
        "legal_basis": _legal_basis_text(rule),
        "legal_basis_detail": rule.get("legal_basis", []),
        "semantic_criteria": detection.get("semantic_criteria"),
        "decision": detection.get("decision"),
        "applies_to": rule.get("applies_to", {}) or {},
        "preconditions": rule.get("preconditions", {}) or {},
        "rule_nature": rule.get("rule_nature") or rule.get("interpretation_type"),
        "routing": rule.get("routing", {}) or {},
        "legal_attention": rule.get("legal_attention", {}) or {},
        "review_required": rule.get("review_required"),
        "source_type": rule.get("source_type"),
        "platform": rule.get("platform"),
        "trigger_layer": _rule_trigger_layer(rule),
    }


_RISK_ORDER = {
    "无明显风险": 0,
    "低": 1,
    "中": 2,
    "高": 3,
    "low": 1,
    "medium": 2,
    "high": 3,
}
_RISK_LABELS = {0: "无明显风险", 1: "低", 2: "中", 3: "高"}


def _risk_rank(value):
    return _RISK_ORDER.get(value or "", 0)


def _risk_label(rank):
    return _RISK_LABELS.get(rank, "无明显风险")


def _is_explicit_hard_guardrail(rule):
    legal_attention = rule.get("legal_attention") or {}
    if not isinstance(legal_attention, dict):
        legal_attention = {}
    if _risk_rank(rule.get("risk_level")) < 3:
        return False
    if legal_attention.get("default_route") != "legal_review_required":
        return False
    return (
        legal_attention.get("risk_severity") in {"high", "高"}
        and (
            legal_attention.get("legal_interpretation_level") == "high"
            or legal_attention.get("fact_verification_level") == "heavy"
            or legal_attention.get("operator_fixability") == "not_self_fixable"
        )
    )


def _synthesize_risk_level(rule_engine_risk_level, llm_risk_level, matched_rules):
    rule_rank = _risk_rank(rule_engine_risk_level)
    llm_rank = _risk_rank(llm_risk_level)
    if not matched_rules or rule_rank == 0:
        return "无明显风险", "no_matched_rules", "未命中有效规则，保持无明显风险。"
    if llm_rank >= 3:
        return "高", "llm_case_high", "LLM 个案判断为高风险，最终风险保持高。"
    if llm_rank >= 2:
        return "中", "llm_case_adjusted", "LLM 个案判断为中风险，最终风险按个案风险确定；法务流转由 routing 单独控制。"
    if llm_rank == 0 and rule_rank >= 2:
        return "中", "minimum_matched_risk", "已有规则命中但 LLM 未确认明显风险，至少保留中风险供人工/运营处理。"
    if llm_rank == 1 and rule_rank >= 2:
        return "中", "minimum_matched_risk", "已有中高风险规则命中，LLM 个案较轻时至少保留中风险。"
    return _risk_label(max(rule_rank, llm_rank)), "max_rule_llm_risk", "规则默认风险等级与 LLM 个案判断取较高值。"

def _risk_level(matched_rules):
    if any(rule.get("risk_level") == "高" for rule in matched_rules):
        return "高"
    if any(rule.get("risk_level") == "中" for rule in matched_rules):
        return "中"
    if matched_rules:
        return "低"
    return "无明显风险"


def _routing(matched_rules):
    routes = []
    fallback_rules = []
    for rule in matched_rules:
        legal_attention = rule.get("legal_attention") or {}
        route = legal_attention.get("default_route") if isinstance(legal_attention, dict) else None
        if route:
            routes.append(route)
        else:
            fallback_rules.append(rule)

    if any(route == "legal_review_required" for route in routes):
        return "\u6cd5\u52a1"
    if routes and not fallback_rules:
        return "\u8fd0\u8425"

    if any(rule.get("routing", {}).get("default_route") == "legal_review_required" for rule in fallback_rules):
        return "\u6cd5\u52a1"
    if any(rule.get("review_required") or rule.get("risk_level") == "\u9ad8" for rule in fallback_rules):
        return "\u6cd5\u52a1"
    return "\u8fd0\u8425"


def _judge_with_config(context_package, matched_rules):
    backend = (os.getenv("ADSURE_LLM_BACKEND") or "mock").lower()
    mode = (os.getenv("ADSURE_LLM_MODE") or "strict").lower()
    if backend in {"deepseek", "real", "llm"}:
        return judge_with_llm(context_package, matched_rules, mode=mode)
    return judge_with_mock_llm(context_package, matched_rules)


def audit(payload, base_dir=None):
    request = map_feishu_payload(payload)
    validate_request(request)

    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent
    if not (base / "jsonbase").exists() and (base.parent / "jsonbase").exists():
        base = base.parent
    library = load_rule_library(base)
    rules = library["data"].get("rules", [])
    context_package = build_context_package(request)
    content_recalled = recall_rules(rules, request, context_package=context_package)
    fact_recalled = fact_recall_rules(rules, request, context_package=context_package)
    recalled = content_recalled + [
        (rule, hits) for rule, hits in fact_recalled
        if rule.get("rule_id") not in {item.get("rule_id") for item, _ in content_recalled}
    ]
    matched_rules = [_matched_rule(rule, hits) for rule, hits in recalled]
    fact_advice = _fact_supplement_advice(fact_recalled)
    raw_high_risk_hits = sorted({hit for _, hits in recalled for hit in hits if not str(hit).startswith("semantic")})
    high_risk_hits = _humanize_hits(raw_high_risk_hits)
    llm_judgment = _judge_with_config(context_package, matched_rules)
    rule_engine_risk_level = _risk_level([rule for rule, _ in recalled])
    llm_risk_level = llm_judgment.get("overall_risk_level") or "无明显风险"
    final_risk_level, final_risk_source, final_risk_reason = _synthesize_risk_level(
        rule_engine_risk_level, llm_risk_level, [rule for rule, _ in recalled]
    )
    risk_assessment = {
        "rule_engine_risk_level": rule_engine_risk_level,
        "llm_risk_level": llm_risk_level,
        "final_risk_level": final_risk_level,
        "risk_disagreement": rule_engine_risk_level != llm_risk_level,
        "risk_disagreement_reason": (
            "规则库默认风险等级与 LLM 个案判断不一致，建议人工复核分歧原因。"
            if rule_engine_risk_level != llm_risk_level
            else "规则库默认风险等级与 LLM 个案判断一致。"
        ),
        "final_risk_source": final_risk_source,
        "final_risk_reason": final_risk_reason,
    }
    risk_level = final_risk_level
    audit_timestamp = int(datetime.now().timestamp() * 1000)

    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "request_id": request.get("request_id"),
            "resolved_mode": "标准",
            "mode_reason": STANDARD_MODE_REASON,
            "预审_风险等级": risk_level,
            "预审_命中要点": _precheck_hit_summary(matched_rules),
            "预审_修改建议": fact_advice or "建议根据命中规则修改文案；如无明显命中，可继续流转确认。",
            "预审_时间": audit_timestamp,
            "审核_审核意见": _compose_audit_opinion(fact_advice, llm_judgment, matched_rules),
            "审核_关键实体抽取": "、".join(
                value
                for value in [
                    context_package.get("industry"),
                    context_package.get("product_category"),
                    "、".join(context_package.get("core_claims", [])),
                    "、".join(context_package.get("platforms", [])),
                ]
                if value
            ),
            "审核_高风险词命中": _precheck_hit_summary(matched_rules) if matched_rules else "无",
            "审核_平台规则预检": "MVP阶段暂按规则库通用规则预检，平台专项规则待扩展。",
            "审核_备案核查结果": fact_advice or "MVP阶段暂未接入备案核查，仅根据运营提交字段做形式提示。",
            "审核_推荐违规类型": sorted(
                {rule.get("dimension") for rule in matched_rules if rule.get("dimension")}
            ),
            "审核_推荐风险等级": risk_level if risk_level != "无明显风险" else "低",
            "risk_assessment": risk_assessment,
            "matched_rules": matched_rules,
            "semantic_recall": {
                "enabled": True,
                "matched_rule_ids": [rule.get("rule_id") for rule in matched_rules if rule.get("recall_channel") == "semantic"],
            },
            "rule_judgments": llm_judgment["rule_judgments"],
            "llm_judgment": llm_judgment,
            "context_package": context_package,
            "routing": _routing([rule for rule, _ in content_recalled]) if content_recalled else "运营",
            "审核_审核时间": audit_timestamp,
            "audit_time": audit_timestamp,
        },
    }

