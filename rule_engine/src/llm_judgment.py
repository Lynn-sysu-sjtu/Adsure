# -*- coding: utf-8 -*-
"""LLM judgment module.

The mock function keeps the current workflow deterministic. The real LLM path
is a replaceable judgment layer: recall still finds candidate rules, and the LLM
only performs legal subsumption and opinion writing.
"""

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

def _rule_judgment(rule):
    risk = rule.get("risk_level") or MEDIUM
    if risk == HIGH:
        judgment = "\u7591\u4f3c\u8fdd\u89c4"
    elif risk == MEDIUM:
        judgment = "\u9700\u8fdb\u4e00\u6b65\u6838\u67e5"
    else:
        judgment = "\u4f4e\u98ce\u9669\u63d0\u793a"
    return {
        "rule_id": rule.get("rule_id"),
        "judgment": judgment,
        "risk_level": risk,
        "reasoning": (
            f"mock LLM \u6839\u636e\u5df2\u53ec\u56de\u89c4\u5219\u300a{rule.get('title', '')}\u300b\u548c\u53ec\u56de\u7406\u7531"
            f"\u201c{rule.get('match_reason', '')}\u201d\u5f62\u6210\u521d\u6b65\u6db5\u6444\u5224\u65ad\u3002"
        ),
        "revision_suggestion": "\u5efa\u8bae\u7ed3\u5408\u8be5\u89c4\u5219\u7684\u6cd5\u5f8b\u4f9d\u636e\u3001\u8bed\u4e49\u5224\u5b9a\u6807\u51c6\u548c\u4e1a\u52a1\u4e8b\u5b9e\u4fee\u6539\u6587\u6848\u6216\u8865\u5145\u8bc1\u660e\u6750\u6599\u3002",
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
    rule_judgments = [_rule_judgment(rule) for rule in matched_rules]
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
        "rule_id": rule.get("rule_id"),
        "serial_no": rule.get("serial_no"),
        "title": rule.get("title"),
        "dimension": rule.get("dimension"),
        "risk_level": rule.get("risk_level"),
        "match_reason": rule.get("match_reason"),
        "recall_channel": rule.get("recall_channel"),
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

    output_contract = {
        "opinion_type": "风险提示/违规修改/需补资料/无明显风险（必须四选一）",
        "overall_risk_level": "\u9ad8/\u4e2d/\u4f4e/\u65e0\u660e\u663e\u98ce\u9669",
        "matched_rules": [
            {
                "rule_id": "string",
                "is_violation": "boolean",
                "risk_level": "\u9ad8/\u4e2d/\u4f4e",
                "reason": "\u4e3a\u4ec0\u4e48\u8be5\u89c4\u5219\u9002\u7528\u6216\u4e0d\u9002\u7528",
                "evidence": "\u6587\u6848\u4e2d\u5bf9\u5e94\u7684\u89e6\u53d1\u8868\u8ff0",
                "legal_basis": "\u89c4\u5219\u6765\u6e90\u6216\u6cd5\u6761\u4f9d\u636e",
            }
        ],
        "outside_rule_risks": ["\u4ec5\u5728\u5019\u9009\u89c4\u5219\u4e0d\u8db3\u65f6\u586b\u5199"],
        "audit_opinion": "面向运营/法务的审核意见，开头应写明意见类型；风险提示表示目前不能直接认定投放前违规，但需要提示履约、证明或披露风险；违规修改表示文案本身已经触发刚性规则，投放前需要修改；需补资料表示缺少判断所需证明材料；无明显风险表示未发现明显规则命中。",
        "revision_suggestion": "\u53ef\u6267\u884c\u7684\u4fee\u6539\u5efa\u8bae",
        "need_legal_review": "boolean",
        "routing": "\u8fd0\u8425/\u6cd5\u52a1",
    }
    payload = {
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
    judgments = []
    for item in parsed.get("matched_rules", []) or []:
        judgments.append(
            {
                "rule_id": item.get("rule_id"),
                "judgment": "\u7591\u4f3c\u8fdd\u89c4" if item.get("is_violation") else "\u672a\u786e\u8ba4\u8fdd\u89c4",
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


