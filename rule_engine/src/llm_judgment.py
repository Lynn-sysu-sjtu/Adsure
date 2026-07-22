# -*- coding: utf-8 -*-
"""LLM judgment module.

The mock function keeps the current workflow deterministic. The real LLM path
is a replaceable judgment layer: recall still finds candidate rules, and the LLM
only performs legal subsumption and opinion writing.
"""

import copy
import json
import re

HIGH = "\u9ad8"
MEDIUM = "\u4e2d"
LOW = "\u4f4e"
NO_OBVIOUS_RISK = "\u65e0\u660e\u663e\u98ce\u9669"
LEGAL_ROUTE = "\u6cd5\u52a1"
OPERATOR_ROUTE = "\u8fd0\u8425"
OPINION_RISK_NOTICE = "风险提示"
OPINION_VIOLATION = "违规修改"
OPINION_NEED_INFO = "需补资料"
OPINION_NO_RISK = "无明显风险"
OPINION_TYPES = [OPINION_RISK_NOTICE, OPINION_VIOLATION, OPINION_NEED_INFO, OPINION_NO_RISK]


def _overall_risk_level(matched_rules):
    if any(rule.get("risk_level") == HIGH for rule in matched_rules):
        return HIGH
    if any(rule.get("risk_level") == MEDIUM for rule in matched_rules):
        return MEDIUM
    if matched_rules:
        return LOW
    return NO_OBVIOUS_RISK


def _default_opinion_type(matched_rules):
    if not matched_rules:
        return OPINION_NO_RISK
    if any(rule.get("recall_channel") == "fact" for rule in matched_rules):
        return OPINION_NEED_INFO
    if any(rule.get("risk_level") == HIGH for rule in matched_rules):
        return OPINION_VIOLATION
    return OPINION_RISK_NOTICE

def _rule_judgment(rule, material_text=""):
    risk = rule.get("risk_level") or MEDIUM
    trigger_layer = (rule.get("recall") or {}).get("trigger_layer") or (
        "fact" if rule.get("recall_channel") == "fact" else "content"
    )
    status = "needs_fact_verification" if trigger_layer == "fact" else "confirmed_violation"
    missing_facts = []
    if status == "needs_fact_verification":
        missing_facts = [
            str(item).removeprefix("\u9700\u8865\u5145")
            for item in rule.get("raw_hit_terms") or []
            if str(item).startswith("\u9700\u8865\u5145")
        ] or ["\u4e0e\u8be5\u4e8b\u5b9e\u5ba3\u79f0\u5bf9\u5e94\u7684\u5907\u6848\u3001\u8d44\u8d28\u6216\u8bc1\u660e\u6750\u6599"]
    return {
        "rule_uid": rule.get("rule_uid"),
        "rule_id": rule.get("rule_id"),
        "applicability_status": status,
        "material_evidence": material_text if status == "confirmed_violation" else "",
        "satisfied_elements": [rule.get("title") or "候选规则相关事实"],
        "unsatisfied_elements": [],
        "missing_facts": missing_facts,
        "applicability_reason": (
            "mock LLM 将事实核验规则保留为需补资料。"
            if status == "needs_fact_verification"
            else "mock LLM 根据候选规则和召回证据确认内容风险。"
        ),
        "confidence": 1.0,
        "judgment": "需事实核验" if status == "needs_fact_verification" else "疑似违规",
        "risk_level": risk,
        "reasoning": f"mock LLM 基于候选规则《{rule.get('title', '')}》形成结构化涵摄判断。",
        "evidence": rule.get("match_reason") or "",
        "legal_basis": rule.get("legal_basis_detail") or rule.get("legal_basis") or [],
        "revision_suggestion": "建议根据适用状态修改文案或补充证明材料。",
    }


def _audit_opinion(overall_risk, matched_rules, rule_judgments):
    if not matched_rules:
        return (
            "\u2460\u98ce\u9669\u5b9a\u6027\uff1amock LLM \u672a\u53d1\u73b0\u660e\u663e\u89c4\u5219\u547d\u4e2d\u3002\n"
            "\u2461\u7981\u7528\u8bcd\uff1a\u65e0\u3002\n"
            "\u2462\u8fdd\u89c4\u7c7b\u578b\uff1a\u65e0\u660e\u663e\u98ce\u9669\u3002\n"
            "\u2463\u6cd5\u5f8b\u4f9d\u636e\uff1a\u6682\u65e0\u547d\u4e2d\u3002\n"
            "\u2464\u4fee\u6539\u5efa\u8bae\uff1a\u53ef\u7ee7\u7eed\u6d41\u8f6c\u786e\u8ba4\uff1b\u5982\u6d89\u53ca\u7279\u6b8a\u54c1\u7c7b\uff0c\u8bf7\u8865\u5145\u5fc5\u8981\u80cc\u666f\u6750\u6599\u3002\n"
            "\u2465\u98ce\u9669\u5b9a\u7ea7\uff1a\u65e0\u660e\u663e\u98ce\u9669\u3002"
        )

    dimensions = "\u3001".join(sorted({rule.get("dimension", "") for rule in matched_rules if rule.get("dimension")}))
    legal_basis = "\u3001".join(str(basis) for rule in matched_rules for basis in rule.get("legal_basis", [])) or "\u8be6\u89c1\u547d\u4e2d\u89c4\u5219"
    suggestions = "\uff1b".join(item["revision_suggestion"] for item in rule_judgments[:2])
    titles = "\u3001".join(rule.get("title", "") for rule in matched_rules[:3])
    return (
        f"\u2460\u98ce\u9669\u5b9a\u6027\uff1amock LLM \u57fa\u4e8e\u53ec\u56de\u89c4\u5219\u521d\u5224\u5b58\u5728{overall_risk}\u98ce\u9669\uff0c\u91cd\u70b9\u6d89\u53ca\uff1a{titles}\u3002\n"
        "\u2461\u7981\u7528\u8bcd\uff1a\u8be6\u89c1\u9ad8\u98ce\u9669\u8bcd\u547d\u4e2d\u3002\n"
        f"\u2462\u8fdd\u89c4\u7c7b\u578b\uff1a{dimensions or '\u5f85\u5224\u65ad'}\u3002\n"
        f"\u2463\u6cd5\u5f8b\u4f9d\u636e\uff1a{legal_basis}\u3002\n"
        f"\u2464\u4fee\u6539\u5efa\u8bae\uff1a{suggestions}\n"
        f"\u2465\u98ce\u9669\u5b9a\u7ea7\uff1a{overall_risk}\u3002"
    )


def judge_with_mock_llm(context_package, matched_rules):
    """Return deterministic LLM-like legal subsumption output."""
    rule_judgments = [
        _rule_judgment(rule, context_package.get("material_text") or "")
        for rule in matched_rules
    ]
    overall_risk = _overall_risk_level(matched_rules)
    return {
        "opinion_type": _default_opinion_type(matched_rules),
        "engine": "mock_llm_v0",
        "overall_risk_level": overall_risk,
        "audit_opinion": _audit_opinion(overall_risk, matched_rules, rule_judgments),
        "rule_judgments": rule_judgments,
        "summary": context_package.get("context_summary", ""),
    }


def _compact_rule_for_llm(rule):
    detection = rule.get("detection", {}) or {}
    return {
        "rule_uid": rule.get("rule_uid"),
        "rule_id": rule.get("rule_id"),
        "serial_no": rule.get("serial_no"),
        "title": rule.get("title"),
        "dimension": rule.get("dimension"),
        "risk_level": rule.get("risk_level"),
        "match_reason": rule.get("match_reason"),
        "recall_channel": rule.get("recall_channel"),
        "trigger_layer": (rule.get("recall") or {}).get("trigger_layer") or rule.get("trigger_layer"),
        "legal_basis": rule.get("legal_basis_detail") or rule.get("legal_basis") or [],
        "semantic_criteria": rule.get("semantic_criteria") or detection.get("semantic_criteria"),
        "decision": rule.get("decision") or detection.get("decision"),
        "applies_to": rule.get("applies_to", {}) or {},
        "preconditions": rule.get("preconditions", {}) or {},
        "rule_nature": rule.get("rule_nature"),
        "routing": rule.get("routing", {}) or {},
        "review_required": rule.get("review_required"),
        "source_type": rule.get("source_type"),
        "platform": rule.get("platform"),
    }


def apply_context_provenance_guard(llm_judgment, candidate_rules, context_package):
    result = copy.deepcopy(llm_judgment)
    conflicts = context_package.get("context_conflicts") or []
    conflict = next(
        (
            item
            for item in conflicts
            if item.get("type") == "declared_industry_denied_by_background"
        ),
        None,
    )
    if not conflict:
        return result

    industry = str(conflict.get("declared_industry") or "").strip()
    candidates_by_uid = {
        item.get("rule_uid"): item
        for item in candidate_rules
        if item.get("rule_uid")
    }
    candidates_by_id = {
        item.get("rule_id"): item
        for item in candidate_rules
        if item.get("rule_id")
    }
    changed = False
    for judgment in result.get("rule_judgments") or []:
        if judgment.get("applicability_status") != "confirmed_violation":
            continue
        candidate = candidates_by_uid.get(judgment.get("rule_uid"))
        if candidate is None:
            candidate = candidates_by_id.get(judgment.get("rule_id"))
        if not candidate:
            continue
        applies_to = candidate.get("applies_to", {}) or {}
        industries = [str(item) for item in (applies_to.get("industries") or [])]
        if not industries or "通用" in industries or industry not in industries:
            continue

        missing_fact = f"核验产品是否属于{industry}及相应资质"
        unsatisfied = f"产品属于{industry}的前提尚未核验"
        reason = (
            "行业字段仅为召回和路由标签，且补充背景明确否认该产品身份；"
            "需先核验产品实际监管属性。"
        )
        judgment["applicability_status"] = "needs_fact_verification"
        judgment["judgment"] = "需事实核验"
        judgment["missing_facts"] = list(judgment.get("missing_facts") or [])
        if missing_fact not in judgment["missing_facts"]:
            judgment["missing_facts"].append(missing_fact)
        judgment["unsatisfied_elements"] = list(
            judgment.get("unsatisfied_elements") or []
        )
        if unsatisfied not in judgment["unsatisfied_elements"]:
            judgment["unsatisfied_elements"].append(unsatisfied)
        judgment["applicability_reason"] = reason
        judgment["reasoning"] = reason
        changed = True

    if changed:
        result["revision_suggestion"] = (
            "删除已确认的直接违法表述，并核验产品实际监管属性；"
            "不得以添加行业专属免责或警示语替代对直接违法文案的删除。"
        )
    return result


def build_judgment_messages(context_package, matched_rules, mode="strict"):
    """Build chat messages for strict or expanded LLM judgment."""
    mode = mode if mode in {"strict", "expanded"} else "strict"
    if mode == "strict":
        mode_policy = (
            "\u4e25\u683c\u89c4\u5219\u5e93\u6a21\u5f0f\uff1a\u4f60\u53ea\u80fd\u57fa\u4e8e\u5019\u9009\u89c4\u5219\u505a\u6db5\u6444\u5224\u65ad\u3002"
            "\u5982\u679c\u5019\u9009\u89c4\u5219\u4e0d\u8db3\u4ee5\u652f\u6301\u5224\u65ad\uff0c\u4e0d\u5f97\u7f16\u9020\u6cd5\u6761\uff0c\u5e94\u5728 outside_rule_risks \u4e2d\u8bf4\u660e\u5f85\u4eba\u5de5\u786e\u8ba4\u3002"
        )
    else:
        mode_policy = (
            "\u6269\u5c55\u98ce\u9669\u63d0\u793a\u6a21\u5f0f\uff1a\u4f18\u5148\u4f7f\u7528\u5019\u9009\u89c4\u5219\u3002"
            "\u5982\u679c\u53d1\u73b0\u660e\u663e\u4f46\u672c\u5730\u89c4\u5219\u5e93\u672a\u8986\u76d6\u7684\u98ce\u9669\uff0c\u53ef\u4ee5\u5199\u5165\u201c\u89c4\u5219\u5e93\u5916\u98ce\u9669\u201d\uff1b\u4f46\u4e0d\u5f97\u4f2a\u9020\u5177\u4f53\u6761\u6587\u6216\u5e73\u53f0\u6765\u6e90\u3002"
        )

    judgment_policy = {
        "identity_field": "rule_uid",
        "require_every_candidate_once": True,
        "keyword_relevance_is_not_applicability": "关键词或语义命中只证明规则相关，不能单独证明规则适用或构成违规。",
        "missing_fact_policy": "依赖备案、资质、证明材料或履约事实时，必须返回needs_fact_verification并列出缺失事实。",
        "missing_fact_boundary": "needs_fact_verification\u53ea\u80fd\u7528\u4e8e\u89c4\u5219\u7684\u524d\u63d0\u4e8b\u5b9e\u5df2\u5728\u7269\u6599\u4e2d\u51fa\u73b0\uff0c\u4f46\u5907\u6848\u3001\u8d44\u8d28\u3001\u8bc1\u660e\u6216\u771f\u5b9e\u6027\u4e8b\u5b9e\u672a\u77e5\u7684\u60c5\u5f62\u3002\u4e0d\u80fd\u7528\u7f3a\u5c11\u8bc1\u660e\u6750\u6599\u4ee3\u66ff\u6784\u6210\u8981\u4ef6\u3002\u4ec5\u51fa\u73b0\u4ea7\u54c1\u540d\u79f0\u6216\u5c5e\u6027\u63cf\u8ff0\uff0c\u6ca1\u6709\u5177\u4f53\u4f7f\u7528\u6548\u679c\u5ba3\u79f0\u65f6\uff0c\u865a\u6784\u6548\u679c\u89c4\u5219\u5e94\u4e3anot_applicable\uff0c\u5907\u6848\u6216\u8d44\u8d28\u89c4\u5219\u53ef\u4e3aneeds_fact_verification\u3002",
        "boundary_examples": [
            {
                "material": "\u8fd9\u662f\u6211\u4eec\u7684\u7f8e\u767d\u7cbe\u534e",
                "cosmetic_filing_rule": "needs_fact_verification",
                "fabricated_effect_rule": "not_applicable",
                "reason": "\u7f8e\u767d\u7cbe\u534e\u662f\u4ea7\u54c1\u540d\u79f0\u6216\u529f\u6548\u5c5e\u6027\u63cf\u8ff0\uff0c\u9700\u6838\u9a8c\u5907\u6848\u7c7b\u522b\uff0c\u4f46\u6ca1\u6709\u58f0\u79f0\u6d88\u8d39\u8005\u5df2\u7ecf\u53d6\u5f97\u5b9e\u9645\u7f8e\u767d\u6548\u679c\uff0c\u4e0d\u80fd\u8fdb\u5165\u865a\u6784\u4f7f\u7528\u6548\u679c\u89c4\u5219\u3002",
            },
            {
                "material": "\u4f7f\u75287\u5929\u5fc5\u5b9a\u767d\u4e09\u4e2a\u8272\u53f7",
                "fabricated_effect_rule": "needs_fact_verification",
                "reason": "\u6587\u6848\u5df2\u5ba3\u79f0\u5177\u4f53\u4f7f\u7528\u6548\u679c\uff0c\u6548\u679c\u771f\u5b9e\u6027\u548c\u8bc1\u660e\u4f9d\u636e\u5f85\u6838\u9a8c\u3002",
            },
            {
                "material": "\u6211\u4eec\u4e00\u964d\u4ef7\uff0c\u4f60\u8fd8\u4e0d\u662f\u50cf\u72d7\u4e00\u6837\u8dd1\u8fc7\u6765",
                "good_customs_rule": "confirmed_violation",
                "missing_facts": [],
                "reason": "\u52a8\u7269\u5316\u8d2c\u635f\u6d88\u8d39\u8005\u7684\u8868\u8fbe\u5df2\u5b8c\u6574\u51fa\u73b0\u5728\u6587\u6848\u4e2d\uff0c\u53ef\u76f4\u63a5\u6839\u636e\u6587\u6848\u539f\u6587\u5b8c\u6210\u4ef7\u503c\u5224\u65ad\uff0c\u4e0d\u5f97\u964d\u7ea7\u4e3aneeds_fact_verification\u3002",
            },
        ],
        "context_provenance_policy": "补充背景为运营提供且未经核验；可用于理解和发现冲突，不得单独支持确定违规。",
        "industry_role_policy": "行业字段只是召回与路由标签，不单独证明产品法律属性。",
        "industry_conflict_policy": "存在行业显式冲突时，依赖该产品身份的专项规则不得仅凭行业字段确认适用。",
        "general_rule_priority": "不依赖产品身份的通用直接内容禁止规则可独立完成判断。",
        "direct_content_priority": "直接内容违规与补资料并存时，直接内容违规是核心风险，补资料只能作为附带核验。",
        "evidence_policy": "confirmed_violation\u5fc5\u987b\u4ece\u7269\u6599\u539f\u6587\u4e2d\u9010\u5b57\u590d\u5236\u4e00\u4e2a\u5355\u4e2a\u8fde\u7eed\u7247\u6bb5\u3002\u4e0d\u5f97\u6539\u5199\u6216\u6982\u62ec\u3002\u4e0d\u5f97\u5220\u9664\u4e2d\u95f4\u6587\u5b57\u540e\u62fc\u63a5\uff1b\u82e5\u591a\u4e2a\u98ce\u9669\u4e8b\u5b9e\u4f4d\u4e8e\u4e0d\u540c\u4f4d\u7f6e\uff0cmaterial_evidence\u53ea\u80fd\u9009\u62e9\u5176\u4e2d\u4e00\u4e2a\u8fde\u7eed\u7247\u6bb5\u3002",
    }
    output_contract = {
        "opinion_type": "风险提示/违规修改/需补资料/无明显风险（必须四选一）",
        "overall_risk_level": "高/中/低/无明显风险",
        "rule_judgments": [
            {
                "rule_uid": "候选规则的全局唯一UID",
                "rule_id": "兼容展示用业务ID",
                "applicability_status": "confirmed_violation | needs_fact_verification | not_applicable",
                "material_evidence": "物料中的连续原文；不适用且无证据时为空字符串",
                "satisfied_elements": ["已经满足的规则构成要件"],
                "unsatisfied_elements": ["尚未满足的规则构成要件"],
                "missing_facts": ["完成判断所需的备案、资质、证明或履约事实"],
                "applicability_reason": "为什么规则适用、待核验或不适用",
                "confidence": "0到1之间的数字",
            }
        ],
        "outside_rule_risks": ["仅在候选规则不足时填写"],
        "audit_opinion": "面向运营/法务的审核意见，开头写明意见类型。",
        "revision_suggestion": "可执行的修改或补资料建议",
        "need_legal_review": "boolean",
        "routing": "运营/法务",
    }
    payload = {
        "judgment_policy": judgment_policy,
        "opinion_type_policy": "必须输出 opinion_type，且只能是：风险提示、违规修改、需补资料、无明显风险。不要把所有规则命中都直接认定为违规；赠送、价格、概率、资质、证明材料等事实或履约类问题，若仅凭文案不能确认违法，应优先归为风险提示或需补资料。",
        "mode": mode,
        "mode_policy": mode_policy,
        "context_package": context_package,
        "candidate_rules": [_compact_rule_for_llm(rule) for rule in matched_rules],
        "output_contract": output_contract,
    }
    system_prompt = (
        "\u4f60\u662f\u5e7f\u544a\u5408\u89c4\u5ba1\u6838\u52a9\u624b\uff0c\u64c5\u957f\u628a\u5e7f\u544a\u6587\u6848\u4e8b\u5b9e\u4e0e\u5df2\u7ed9\u5b9a\u7684\u6cd5\u89c4/\u5e73\u53f0\u89c4\u5219\u8fdb\u884c\u6db5\u6444\u5224\u65ad\u3002"
        "\u8bf7\u53ea\u8f93\u51fa JSON\uff0c\u4e0d\u8981\u8f93\u51fa markdown\u3002"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
    ]


def _extract_message_content(response):
    if isinstance(response, str):
        return response
    return response.get("choices", [{}])[0].get("message", {}).get("content", "")


def _parse_json_content(content):
    content = str(content or "").strip()
    content = re.sub(r"^```(?:json)?", "", content).strip()
    content = re.sub(r"```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _rule_judgments_from_llm(parsed):
    structured = parsed.get("rule_judgments")
    if isinstance(structured, list):
        judgments = []
        for item in structured:
            if not isinstance(item, dict):
                continue
            status = item.get("applicability_status")
            judgments.append(
                {
                    "rule_uid": item.get("rule_uid"),
                    "rule_id": item.get("rule_id"),
                    "applicability_status": status,
                    "material_evidence": item.get("material_evidence") or "",
                    "satisfied_elements": item.get("satisfied_elements") or [],
                    "unsatisfied_elements": item.get("unsatisfied_elements") or [],
                    "missing_facts": item.get("missing_facts") or [],
                    "applicability_reason": item.get("applicability_reason") or "",
                    "confidence": item.get("confidence"),
                    "judgment": "确认适用" if status == "confirmed_violation" else (
                        "需事实核验" if status == "needs_fact_verification" else "不适用"
                    ),
                    "risk_level": item.get("risk_level") or MEDIUM,
                    "reasoning": item.get("applicability_reason") or "",
                    "evidence": item.get("material_evidence") or "",
                    "legal_basis": item.get("legal_basis") or "",
                    "revision_suggestion": parsed.get("revision_suggestion") or "",
                }
            )
        return judgments

    judgments = []
    for item in parsed.get("matched_rules", []) or []:
        judgments.append(
            {
                "rule_uid": item.get("rule_uid"),
                "rule_id": item.get("rule_id"),
                "judgment": "疑似违规" if item.get("is_violation") else "未确认违规",
                "risk_level": item.get("risk_level") or MEDIUM,
                "reasoning": item.get("reason") or "",
                "evidence": item.get("evidence") or "",
                "legal_basis": item.get("legal_basis") or "",
                "revision_suggestion": parsed.get("revision_suggestion") or "",
            }
        )
    return judgments


def judge_with_llm(context_package, matched_rules, mode="strict", client=None, model=None):
    """Call a real chat model and normalize its JSON judgment."""
    if client is None:
        from deepseek_client import DeepSeekClient

        client = DeepSeekClient(model=model)
    messages = build_judgment_messages(context_package, matched_rules, mode=mode)
    response = client.create_chat_completion(
        messages,
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    content = _extract_message_content(response)
    try:
        parsed = _parse_json_content(content)
    except Exception as exc:  # pragma: no cover - defensive fallback for provider drift
        return {
            "engine": "deepseek_llm_v0",
            "mode": mode,
            "opinion_type": OPINION_RISK_NOTICE,
            "overall_risk_level": MEDIUM,
            "audit_opinion": content,
            "rule_judgments": [],
            "summary": context_package.get("context_summary", ""),
            "outside_rule_risks": ["LLM \u8fd4\u56de\u4e0d\u662f\u53ef\u89e3\u6790 JSON\uff0c\u9700\u4eba\u5de5\u590d\u6838\u3002"],
            "revision_suggestion": "\u8bf7\u4eba\u5de5\u590d\u6838 LLM \u539f\u59cb\u8f93\u51fa\u3002",
            "need_legal_review": True,
            "routing": LEGAL_ROUTE,
            "parse_error": str(exc),
        }

    return {
        "engine": "deepseek_llm_v0",
        "mode": mode if mode in {"strict", "expanded"} else "strict",
        "opinion_type": parsed.get("opinion_type") if parsed.get("opinion_type") in OPINION_TYPES else _default_opinion_type(matched_rules),
        "overall_risk_level": parsed.get("overall_risk_level") or _overall_risk_level(matched_rules),
        "audit_opinion": parsed.get("audit_opinion") or "",
        "rule_judgments": _rule_judgments_from_llm(parsed),
        "summary": context_package.get("context_summary", ""),
        "outside_rule_risks": parsed.get("outside_rule_risks") or [],
        "revision_suggestion": parsed.get("revision_suggestion") or "",
        "need_legal_review": bool(parsed.get("need_legal_review")),
        "routing": parsed.get("routing") or (LEGAL_ROUTE if parsed.get("need_legal_review") else OPERATOR_ROUTE),
        "raw_response": parsed,
    }


