# -*- coding: utf-8 -*-
"""Bounded LLM catalog recall for explicitly enabled open-ended rules."""

import json
import os
import re

from catalog_rule_directory import build_catalog_directory


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _catalog_limit(value=None):
    if value is not None:
        return max(1, int(value))
    raw = os.getenv("ADSURE_CATALOG_RECALL_LIMIT")
    if raw not in (None, ""):
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 1


def build_catalog_messages(context_package, directory, limit=1):
    system_prompt = (
        "你是高精度广告合规规则目录召回器。默认返回空数组，宁可漏召回也不要泛化猜测。"
        "只有物料原文直接、具体地表达了目录规则的核心行为时才能选择该rule_id；"
        "一般性的促销、点击、效果、资质、广告标识或合规担忧，不足以召回开放性规则。"
        "每条选择必须引用物料中的连续原文证据；没有原文证据、仅有间接关联或不确定时不得选择。"
        "已有候选规则已经实质覆盖同一行为时，不得重复选择含义更宽泛的开放性规则；"
        "只有存在独立且未被已有候选覆盖的开放性风险时才可补充目录规则。"
        "你只能从给定目录选择rule_id；不得判断是否违法，不得输出风险等级，不得生成目录外规则。只输出JSON。"
    )
    payload = {
        "task": "选择可能与物料表达相关的开放性规则，最多选择指定数量；不做法律结论。",
        "selection_limit": _catalog_limit(limit),
        "material_context": {
            "content": context_package.get("material_text") or context_package.get("content") or "",
            "industry": context_package.get("industry") or "",
            "material_type": context_package.get("material_type") or "",
            "platforms": context_package.get("platforms") or [],
            "product_category": context_package.get("product_category") or "",
            "core_claims": context_package.get("core_claims") or [],
            "scenario": context_package.get("scenario") or "",
        },
        "existing_candidate_rules": context_package.get("existing_candidate_rules") or [],
        "rule_directory": directory,
        "output_contract": {
            "selected_rules": [
                {
                    "rule_id": "目录中的rule_id",
                    "evidence": "物料中的连续原文证据",
                    "reason": "证据与目录规则核心行为的直接对应关系，不判断违法",
                }
            ]
        },
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def _parsed_catalog_payload(response):
    if isinstance(response, dict):
        return response
    text = str(response or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalized_evidence(value):
    return "".join(str(value or "").split())


def parse_catalog_selections(
    response,
    allowed_ids,
    limit=1,
    material_text="",
    require_evidence=False,
):
    parsed = _parsed_catalog_payload(response)
    raw_items = parsed.get("selected_rules")
    if isinstance(raw_items, list):
        candidates = [item for item in raw_items if isinstance(item, dict)]
    elif not require_evidence:
        selected_ids = parsed.get("selected_rule_ids") or []
        candidates = [
            {"rule_id": rule_id, "evidence": "", "reason": parsed.get("reason") or ""}
            for rule_id in selected_ids
        ] if isinstance(selected_ids, list) else []
    else:
        candidates = []

    content = _normalized_evidence(material_text)
    selections = []
    seen_ids = set()
    for item in candidates:
        rule_id = item.get("rule_id")
        evidence = str(item.get("evidence") or "").strip()
        reason = str(item.get("reason") or "目录模型召回").strip()
        if rule_id not in allowed_ids or rule_id in seen_ids:
            continue
        if require_evidence:
            normalized = _normalized_evidence(evidence)
            if not normalized or normalized not in content:
                continue
        seen_ids.add(rule_id)
        selections.append(
            {
                "rule_id": rule_id,
                "evidence": evidence,
                "reason": reason,
            }
        )
        if len(selections) >= _catalog_limit(limit):
            break
    return selections


def parse_catalog_response(response, allowed_ids, limit=1):
    return [
        item["rule_id"]
        for item in parse_catalog_selections(response, allowed_ids, limit=limit)
    ]


def catalog_recall_rules(
    rules,
    request,
    context_package,
    backend=None,
    enabled=None,
    limit=None,
    mock_response=None,
    client=None,
):
    enabled = _env_bool("ADSURE_CATALOG_RECALL_ENABLED") if enabled is None else bool(enabled)
    if not enabled:
        return []
    directory = build_catalog_directory(rules, request)
    if not directory:
        return []
    backend = (backend or os.getenv("ADSURE_CATALOG_LLM_BACKEND") or "mock").lower()
    if backend == "mock":
        response = mock_response if mock_response is not None else {"selected_rule_ids": [], "reason": ""}
    elif backend in {"deepseek", "real", "llm"}:
        try:
            if client is None:
                from deepseek_client import DeepSeekClient

                raw_timeout = os.getenv("ADSURE_CATALOG_LLM_TIMEOUT") or "4"
                try:
                    timeout = max(1, int(raw_timeout))
                except ValueError:
                    timeout = 4
                model = os.getenv("ADSURE_CATALOG_LLM_MODEL") or "deepseek-chat"
                client = DeepSeekClient(model=model, timeout=timeout)
            model = os.getenv("ADSURE_CATALOG_LLM_MODEL") or "deepseek-chat"
            api_response = client.create_chat_completion(
                build_catalog_messages(context_package, directory, limit=_catalog_limit(limit)),
                model=model,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            response = (
                (api_response.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
            )
        except Exception:
            return []
    else:
        return []
    allowed_ids = {item["rule_id"] for item in directory}
    selections = parse_catalog_selections(
        response,
        allowed_ids,
        limit=_catalog_limit(limit),
        material_text=context_package.get("material_text") or "",
        require_evidence=backend in {"deepseek", "real", "llm"},
    )
    rules_by_id = {rule.get("rule_id"): rule for rule in rules}
    recalled = []
    for item in selections:
        rule = rules_by_id.get(item["rule_id"])
        if not rule:
            continue
        reason = item.get("reason") or "目录模型召回"
        evidence = item.get("evidence") or ""
        hit = f"llm_catalog:{reason}"
        if evidence:
            hit += f":evidence={evidence}"
        recalled.append((rule, [hit]))
    return recalled
