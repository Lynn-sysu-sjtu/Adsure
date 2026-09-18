# -*- coding: utf-8 -*-
"""V2 DeepSeek contract for legal-issue candidate asset generation."""

import json

import legal_issue_candidate_pipeline_v1 as _v1
from legal_issue_candidate_pipeline_v1 import *  # noqa: F401,F403


ALLOWED_INPUT_FIELDS = (
    "rule_uid", "rule_id", "title", "dimension", "industry", "platform",
    "source_type", "applies_to", "legal_basis", "detection", "recall",
    "rule_applicability", "fact_check", "legal_attention",
)


def build_candidate_messages(rule, source_file):
    selected = {key: rule.get(key) for key in ALLOWED_INPUT_FIELDS if key in rule}
    payload = {
        "task": "依据现有规则生成法律问题路径、成立要件、证据权限和主动核查候选，不判断具体广告。",
        "source_file": source_file,
        "rule": selected,
        "evidence_tiers": {
            "core": ["rule_uid", "rule_id", "title", "legal_basis", "applies_to", "rule_applicability", "source_type", "platform"],
            "supporting": ["dimension", "detection", "recall", "legal_attention"],
            "unreviewed_hint": ["fact_check"],
        },
        "allowed_enums": {
            "namespace": sorted(NAMESPACES),
            "evidence_sources": sorted(EVIDENCE_SOURCES),
            "terminal_outcomes": sorted(TERMINAL_OUTCOMES),
            "check_types": ["fact_verification", "qualification", "disclosure", "workflow"],
        },
        "output_contract": {
            "rule_uid": "必须与输入完全相同",
            "issue_candidates": [{
                "namespace": "GEN/GAME/COSM/HF",
                "category_key": "大写英文或下划线",
                "issue_key": "大写英文或下划线",
                "name": "中文问题名称",
                "definition": "问题定义",
                "in_scope": ["纳入情形"],
                "out_of_scope": ["排除情形"],
                "claim_types": ["snake_case"],
                "relationship": "primary或secondary",
            }],
            "elements": [{"element_id": "snake_case", "description": "成立要件", "required": True, "allowed_evidence_sources": ["content/context/fact_state/llm_signal"]}],
            "evidence_policy": {"content": "can_confirm/trigger_only/not_allowed", "context": "scope_only/support_or_refute/not_allowed", "fact_state": "support_or_refute/required_to_confirm/not_allowed", "llm_signal": "candidate_only"},
            "default_terminal_outcome": "confirmed_violation/evidence_required/proactive_check/no_applicable_rule",
            "proactive_check": {
                "check_key": "大写英文或下划线",
                "name": "中文核查事项名称",
                "check_type": "fact_verification/qualification/disclosure/workflow",
                "applicability": {"industries": [], "platforms": [], "material_types": []},
                "trigger_conditions": {"all": [], "any": [], "exclude": []},
                "requirement": "需要核验的具体义务",
                "required_materials": [],
                "default_severity": "高/中/低",
            },
            "quality_flags": [],
            "confidence": "high/medium/low",
            "reason": "说明使用的核心依据及推导过程",
        },
    }
    system = (
        "你是广告合规规则资产结构化助手。你的任务是整理规则资产，不是判断具体广告是否违法，也不是补充法律知识。"
        "核心依据为rule_uid、rule_id、title、legal_basis、applies_to、rule_applicability、source_type、platform；"
        "辅助参考为dimension、detection、recall、legal_attention；fact_check仅是未审核提示。"
        "fact_check不得单独决定法律问题路径、成立要件、主动核查项或终止结果。若fact_check与title、legal_basis或rule_applicability不一致，必须忽略fact_check，并在quality_flags中标记FACT_CHECK_CONFLICT。"
        "不得新增、改写或补充法条、平台条款、法律原文、rule_uid或rule_id，不得引用模型记忆中的法律内容。"
        "不得根据关键词联想输入规则未直接规制的问题，不得将context、fact_state或llm_signal当成正文违规证据。"
        "GEN只用于不依赖特定行业对象或至少能在两个赛道成立的问题。游戏版号、抽卡机制、未成年人游戏付费必须进入GAME；"
        "化妆品备案、特殊化妆品和化妆品功效评价必须进入COSM；保健食品审查、保健功能和法定警示语必须进入HF。"
        "issue_candidates中必须有且仅有一个relationship=primary，其余只能为secondary；primary必须是最直接、最核心的规制问题。"
        "只有title、legal_basis或rule_applicability直接支持额外资料、资质、披露或流程核验时才生成proactive_check；否则proactive_check必须为null，不得猜测，也不得仅根据旧fact_check材料清单生成。"
        "default_terminal_outcome只能是confirmed_violation、evidence_required、proactive_check、no_applicable_rule之一。"
        "输出必须是严格JSON对象且必须包含quality_flags字符串数组；不确定时降低confidence，不得猜测。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]


def parse_candidate_response(response, expected_rule_uid):
    parsed = _v1.parse_candidate_response(response, expected_rule_uid)
    quality_flags = parsed.get("quality_flags")
    if not isinstance(quality_flags, list) or not all(isinstance(item, str) for item in quality_flags):
        raise ValueError("quality_flags must be a string array")
    return parsed


def compile_draft_assets(records, candidates, snapshot):
    issues, mappings, checks = _v1.compile_draft_assets(records, candidates, snapshot)
    for issue in issues.get("issues") or []:
        (issue.get("generation") or {})["prompt_version"] = "legal_issue_candidate_v2"
    return issues, mappings, checks
