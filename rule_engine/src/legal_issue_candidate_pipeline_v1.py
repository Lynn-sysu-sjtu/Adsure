# -*- coding: utf-8 -*-
"""DeepSeek-only candidate generation helpers for legal-issue draft assets."""

import json
import re
from collections import defaultdict
from datetime import datetime, timezone


ALLOWED_INPUT_FIELDS = (
    "rule_uid", "rule_id", "title", "dimension", "industry", "platform",
    "applies_to", "legal_basis", "detection", "recall", "rule_applicability",
    "fact_check", "legal_attention",
)
NAMESPACES = {"GEN", "GAME", "COSM", "HF"}
TRACKS = ("游戏", "美妆", "保健食品")
EVIDENCE_SOURCES = {"content", "context", "fact_state", "llm_signal"}
TERMINAL_OUTCOMES = {"confirmed_violation", "evidence_required", "proactive_check", "no_applicable_rule"}
FORBIDDEN_MODEL_KEYS = {"legal_basis", "law", "laws", "article", "articles", "legal_text", "rule_id"}


def build_candidate_messages(rule, source_file):
    selected = {key: rule.get(key) for key in ALLOWED_INPUT_FIELDS if key in rule}
    payload = {
        "task": "依据现有规则生成法律问题路径、成立要件、证据权限和主动核查候选，不判断具体广告。",
        "source_file": source_file,
        "rule": selected,
        "allowed_enums": {
            "namespace": sorted(NAMESPACES),
            "evidence_sources": sorted(EVIDENCE_SOURCES),
            "terminal_outcomes": sorted(TERMINAL_OUTCOMES),
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
            "elements": [{"element_id": "snake_case", "description": "成立要件", "required": True, "allowed_evidence_sources": ["content"]}],
            "evidence_policy": {"content": "can_confirm/trigger_only/not_allowed", "context": "scope_only/support_or_refute/not_allowed", "fact_state": "support_or_refute/required_to_confirm/not_allowed", "llm_signal": "candidate_only"},
            "default_terminal_outcome": "固定枚举值",
            "proactive_check": None,
            "confidence": "high/medium/low",
            "reason": "仅解释输入规则为何对应这些候选",
        },
    }
    system = (
        "你是广告合规规则资产结构化助手，不是案件裁判者。只能处理输入中的真实规则。"
        "不得新增法条、平台条款、rule_uid或rule_id，不得引用模型记忆中的法律内容。"
        "legal_basis仅供理解和回溯，不得复制到输出。上下文只能限定范围，不能充当正文违规证据。"
        "输出必须是严格JSON对象；不确定时降低confidence，不得猜测。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]


def _parse_json_object(response):
    if isinstance(response, dict):
        return response
    text = str(response or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek candidate response must be a JSON object")
    return parsed


def _contains_forbidden_key(value):
    if isinstance(value, dict):
        return any(key in FORBIDDEN_MODEL_KEYS or _contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _stable_key(value):
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip().upper())
    return re.sub(r"_+", "_", text).strip("_")


def parse_candidate_response(response, expected_rule_uid):
    parsed = _parse_json_object(response)
    if parsed.get("rule_uid") != expected_rule_uid:
        raise ValueError("DeepSeek response rule_uid does not match input rule_uid")
    if _contains_forbidden_key({key: value for key, value in parsed.items() if key != "rule_uid"}):
        raise ValueError("DeepSeek response contains forbidden legal or rule identifier fields")
    candidates = parsed.get("issue_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("DeepSeek response requires at least one issue candidate")
    primary_count = 0
    for item in candidates:
        if item.get("namespace") not in NAMESPACES:
            raise ValueError("invalid issue namespace")
        item["category_key"] = _stable_key(item.get("category_key"))
        item["issue_key"] = _stable_key(item.get("issue_key"))
        if not item["category_key"] or not item["issue_key"]:
            raise ValueError("issue keys must be stable ASCII identifiers")
        if item.get("relationship") == "primary":
            primary_count += 1
    if primary_count != 1:
        raise ValueError("DeepSeek response requires exactly one primary issue")
    if parsed.get("default_terminal_outcome") not in TERMINAL_OUTCOMES:
        raise ValueError("invalid default_terminal_outcome")
    for element in parsed.get("elements") or []:
        sources = set(element.get("allowed_evidence_sources") or [])
        if not sources or not sources <= EVIDENCE_SOURCES:
            raise ValueError("invalid allowed_evidence_sources")
    return parsed


def select_smoke_rules(records, per_track=5):
    selected = []
    for track in TRACKS:
        candidates = sorted(
            (item for item in records if item.get("track") == track),
            key=lambda item: (str(item["rule"].get("dimension") or ""), str(item["rule"].get("rule_uid") or "")),
        )
        used_dimensions = set()
        deferred = []
        for item in candidates:
            dimension = str(item["rule"].get("dimension") or "")
            if dimension and dimension not in used_dimensions and len([row for row in selected if row.get("track") == track]) < per_track:
                selected.append(item)
                used_dimensions.add(dimension)
            else:
                deferred.append(item)
        remaining = per_track - len([row for row in selected if row.get("track") == track])
        if remaining > 0:
            selected.extend(deferred[:remaining])
    return selected


def _review():
    return {"status": "pending", "reviewer": None, "reviewed_at": None, "notes": None}


def _issue_id(candidate):
    return ".".join((candidate["namespace"], candidate["category_key"], candidate["issue_key"]))


def compile_draft_assets(records, candidates, snapshot):
    records_by_uid = {item["rule"]["rule_uid"]: item for item in records}
    issue_groups = defaultdict(list)
    for candidate in candidates:
        for issue in candidate["issue_candidates"]:
            issue_groups[_issue_id(issue)].append((candidate, issue))
    issues = []
    for issue_id in sorted(issue_groups):
        proposals = issue_groups[issue_id]
        first_candidate, first = proposals[0]
        rule_uids = sorted({candidate["rule_uid"] for candidate, _ in proposals})
        track = "通用" if first["namespace"] == "GEN" else {"GAME": "游戏", "COSM": "美妆", "HF": "保健食品"}[first["namespace"]]
        issues.append({
            "issue_id": issue_id, "name": first["name"], "track": track, "parent_issue_id": None,
            "issue_path": [first["namespace"], first["category_key"], first["issue_key"]], "definition": first["definition"],
            "in_scope": list(first.get("in_scope") or []), "out_of_scope": list(first.get("out_of_scope") or []),
            "claim_types": sorted({value for _, item in proposals for value in item.get("claim_types") or []}),
            "default_evidence_policy": first_candidate["evidence_policy"], "candidate_rule_uids": rule_uids,
            "review": _review(), "generation": {"model": "deepseek-chat", "prompt_version": "legal_issue_candidate_v1", "confidence": first_candidate["confidence"], "reason": first_candidate["reason"]},
        })
    mappings = []
    checks_by_id = {}
    for candidate in candidates:
        uid = candidate["rule_uid"]
        record = records_by_uid[uid]
        primary = next(item for item in candidate["issue_candidates"] if item["relationship"] == "primary")
        secondary = [_issue_id(item) for item in candidate["issue_candidates"] if item["relationship"] == "secondary"]
        proactive = candidate.get("proactive_check")
        proactive_ids = []
        if isinstance(proactive, dict):
            check_key = _stable_key(proactive.get("check_key") or "CHECK")
            check_id = f"{_issue_id(primary)}.{check_key}"
            proactive_ids.append(check_id)
            checks_by_id.setdefault(check_id, {
                "check_id": check_id, "name": proactive["name"], "check_type": proactive["check_type"],
                "track": record["track"], "trigger_issue_ids": [_issue_id(primary)],
                "applicability": proactive.get("applicability") or {"industries": [], "platforms": [], "material_types": []},
                "trigger_conditions": proactive.get("trigger_conditions") or {"all": [], "any": [], "exclude": []},
                "requirement": proactive["requirement"], "required_materials": list(proactive.get("required_materials") or []),
                "core_support": list(proactive.get("core_support") or []),
                "basis_rule_uids": [uid], "default_status": "需要核验", "default_severity": proactive.get("default_severity") or "中", "review": _review(),
            })
        mappings.append({
            "rule_uid": uid, "rule_id": record["rule"].get("rule_id") or "", "source_file": record["source_file"],
            "primary_issue_id": _issue_id(primary), "secondary_issue_ids": secondary, "elements": candidate.get("elements") or [],
            "evidence_policy": candidate["evidence_policy"], "default_terminal_outcome": candidate["default_terminal_outcome"],
            "proactive_check_ids": proactive_ids, "mapping_confidence": candidate["confidence"], "mapping_reason": candidate["reason"], "review": _review(),
        })
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    issue_asset = {"schema_version": "0.1", "asset_status": "draft", "generated_at": now, "source_snapshot": snapshot, "issues": issues}
    mapping_asset = {"schema_version": "0.1", "asset_status": "draft", "mappings": mappings}
    check_asset = {"schema_version": "0.1", "asset_status": "draft", "checks": [checks_by_id[key] for key in sorted(checks_by_id)]}
    return issue_asset, mapping_asset, check_asset
