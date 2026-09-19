"""Deterministic /audit adapter for the Feishu state-machine v0.2 contract.

The adapter returns risk candidates and evidence gaps, never a final legality finding.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any

from src.video_mvp.models import EvidenceUnit
from src.video_mvp.rules import analyze_rules

MODES = {"标准", "极速", "深度"}
INDUSTRIES = {"美妆", "游戏", "保健食品", "通用"}
URGENCIES = {"普通", "加急"}
MATERIAL_TYPES = {"图文", "短视频", "直播话术", "Banner", "详情页", "其他"}
LEVEL = {"high": "高", "medium": "中", "low": "低"}
TYPE_MAP = {
    "绝对化用语": "绝对化用语",
    "疾病治疗功效宣传": "涉医疗宣传",
    "功效安全性保证": "虚假宣传",
    "量化功效与引证待核验": "引证内容不规范",
    "权威背书待核验": "广告代言不合规",
    "赠送承诺条件与兑现待核验": "价格促销误导",
    "贬损与不当表达待复核": "其他",
    "投资回报保证待核验": "虚假宣传",
    "教育培训效果保证待核验": "虚假宣传",
    "化妆品功效宣称待核验": "虚假宣传",
    "前后对比效果待核验": "虚假宣传",
    "专利与技术背书待核验": "引证内容不规范",
}
FACT_PATTERNS = {"safety_guarantee", "quantified_effect", "authority_endorsement", "promotional_offer",
                 "cosmetic_efficacy", "absolute_safety_or_edible", "before_after_effect", "patent_claim"}


def _field(fields: dict, exact: str, suffix: str = ""):
    if exact in fields:
        return fields[exact]
    return next((value for key, value in fields.items() if suffix and key.endswith(suffix)), None)


def normalize_request(payload: Any, max_content_length: int) -> tuple[dict | None, str | None]:
    if not isinstance(payload, dict):
        return None, "请求体必须是 JSON 对象"
    if "human_reference" in payload or "provenance" in payload:
        return None, "线上 /audit 不接收 human_reference 或 provenance"
    record_id = payload.get("record_id")
    mode = payload.get("mode", "标准")
    if not isinstance(record_id, str) or not record_id.strip() or len(record_id.strip()) > 128:
        return None, "缺少或无效字段：record_id"
    if mode not in MODES:
        return None, "mode 必须是：标准、极速或深度"

    if isinstance(payload.get("fields"), dict):
        fields = payload["fields"]
        industry = _field(fields, "①运营·行业领域")
        content = _field(fields, "①运营·物料内容")
        urgency = _field(fields, "①运营·紧急程度") or "普通"
        supplement = _field(fields, "①运营·补充背景资料") or ""
        platform = _field(fields, "", "·投放平台") or []
        material_type = _field(fields, "", "·物料类型") or "其他"
        product_category = _field(fields, "", "·产品品类") or ""
        known = {"①运营·行业领域", "①运营·物料内容", "①运营·紧急程度", "①运营·补充背景资料"}
        extras = {key.split("·", 1)[-1]: value for key, value in fields.items()
                  if key not in known and not key.endswith(("·投放平台", "·物料类型", "·产品品类"))}
    else:
        industry, content = payload.get("industry"), payload.get("content")
        urgency, supplement = payload.get("urgency", "普通"), payload.get("supplement", "")
        platform, material_type = payload.get("platform", []), payload.get("material_type", "其他")
        product_category, extras = payload.get("product_category", ""), payload.get("extras", {})
    if industry not in INDUSTRIES:
        return None, "industry 必须是：美妆、游戏、保健食品或通用"
    if not isinstance(content, str) or not content.strip():
        return None, "缺少必填字段：①运营·物料内容"
    if len(content.strip()) > max_content_length:
        return None, f"content 长度不能超过 {max_content_length}"
    if urgency not in URGENCIES:
        return None, "urgency 必须是：普通或加急"
    if not isinstance(supplement, str):
        return None, "supplement 必须是字符串"
    if not isinstance(platform, list) or not platform or any(not isinstance(x, str) or not x.strip() for x in platform):
        return None, "platform 必须是至少包含一个平台的字符串数组"
    if material_type not in MATERIAL_TYPES:
        return None, "material_type 枚举无效"
    if not isinstance(product_category, str):
        return None, "product_category 必须是字符串"
    if not isinstance(extras, dict):
        return None, "extras 必须是对象"
    return {"record_id": record_id.strip(), "mode": mode, "industry": industry,
            "content": content.strip(), "urgency": urgency, "supplement": supplement.strip(),
            "platform": list(dict.fromkeys(x.strip() for x in platform)),
            "material_type": material_type, "product_category": product_category.strip(), "extras": extras}, None


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(x) for x in value if str(x).strip())
    return str(value).strip() if value is not None else ""


def _basis(risk: dict) -> list[str]:
    values = []
    for item in risk.get("legal_basis", []):
        if not isinstance(item, dict):
            continue
        title = item.get("document_title") or item.get("source_name") or "《中华人民共和国广告法》"
        article = item.get("article", "")
        values.append(f"{title}{article}".strip())
    return list(dict.fromkeys(values))


def _aggregate_matched(matched: list[dict]) -> list[dict]:
    """Return one stable Feishu item per rule id while retaining all evidence."""
    unique = {}
    route_rank = {"运营": 0, "运营补资料": 1, "法务": 2}
    level_rank = {"低": 0, "中": 1, "高": 2}
    for item in matched:
        current = unique.get(item["rule_id"])
        if current is None:
            unique[item["rule_id"]] = item
            continue
        for key, separator in (("title", "；"), ("dimension", "、"), ("match_reason", "；"),
                               ("material_evidence", "\n"), ("applicability_reason", "；")):
            values = list(dict.fromkeys(filter(None, [current.get(key, ""), item.get(key, "")])))
            current[key] = separator.join(values)
        for key in ("legal_basis", "satisfied_elements", "unsatisfied_elements", "missing_facts"):
            current[key] = list(dict.fromkeys(current.get(key, []) + item.get(key, [])))
        if route_rank[item["default_routing"]] > route_rank[current["default_routing"]]:
            current["default_routing"] = item["default_routing"]
        if level_rank[item["risk_level"]] > level_rank[current["risk_level"]]:
            current["risk_level"] = item["risk_level"]
    result = list(unique.values())
    for serial, item in enumerate(result, 1):
        item["serial_no"] = serial
    return result


def build_response(payload: dict, *, now_ms: int | None = None) -> dict:
    unit = EvidenceUnit(id="feishu_content", source="user_text", kind="text", text=payload["content"],
                        t_start=0.0, t_end=0.0, provider="feishu_request",
                        raw_ref={"provenance": "record_content_not_fact_verified"})
    engine_industry = {"美妆": "化妆品", "保健食品": "保健食品"}.get(payload["industry"], "一般行业")
    risks, _ = analyze_rules([unit], industry=engine_industry, frame_count=0,
                             coverage_complete=False, sample_interval=.5)
    raw = [r.to_dict() for r in risks]
    raw.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}.get(r["severity"], 3), r["risk_id"]))
    highest = raw[0]["severity"] if raw else "low"
    pre_level = LEVEL[highest] if raw else "无明显风险"
    legal_level = LEVEL[highest]
    matched = []
    serial = 0
    for risk in raw:
        needs_facts = risk.get("pattern_id") in FACT_PATTERNS or risk["severity"] != "high"
        default_route = "运营补资料" if risk.get("pattern_id") in FACT_PATTERNS else "法务" if risk["severity"] == "high" else "运营"
        for rule_id in risk["rule_ids"]:
            serial += 1
            matched.append({
                "rule_id": rule_id, "rule_uid": hashlib.sha256(f"adsure-rule|{rule_id}".encode()).hexdigest()[:24],
                "title": risk["title"], "dimension": risk["risk_dimension"],
                "risk_level": LEVEL[risk["severity"]],
                "judgment": "命中风险候选，需结合物料语境、产品属性及证明材料人工判断",
                "match_reason": f"物料原文命中“{risk['matched_text']}”", "default_routing": default_route,
                "legal_basis": _basis(risk), "applicability_status": "needs_fact_verification",
                "confidence": None, "material_evidence": risk.get("context_text") or risk["matched_text"],
                "satisfied_elements": ["物料中存在对应字面表达"],
                "unsatisfied_elements": ["尚未完成人工语境及事实核验"],
                "missing_facts": ["产品法律属性", "主张对应证明材料"] if needs_facts else ["完整投放语境"],
                "applicability_reason": risk["explanation"], "serial_no": serial,
            })
    matched = _aggregate_matched(matched)
    routing = "法务" if any(r["default_routing"] == "法务" for r in matched) else "运营"
    types = list(dict.fromkeys(TYPE_MAP.get(r["risk_dimension"], "其他") for r in raw))
    words = list(dict.fromkeys(r["matched_text"] for r in raw))
    entities = [payload["product_category"], *payload["platform"]]
    for key, value in payload["extras"].items():
        if any(term in key for term in ("名称", "功效", "场景", "品牌", "IP")):
            entities.append(_text(value))
    entities = list(dict.fromkeys(x for x in entities if x))
    if raw:
        hit_summary = "；".join(f"{r['risk_dimension']}：{r['matched_text']}" for r in raw)[:80]
        advice = "；".join(dict.fromkeys(r["recommendation"] for r in raw))[:100]
    else:
        hit_summary = "未命中当前规则库的字面风险候选，仍需结合完整素材和行业规则人工复核。"[:80]
        advice = "核对完整图像、音频、落地页、资质及平台现行规则后再决定投放。"[:100]
    bases = list(dict.fromkeys(x for r in matched for x in r["legal_basis"]))
    opinion = (f"①风险定性：当前生成{len(matched)}项机器风险候选，不构成违法认定。\n"
               f"②违禁词鉴别：{'、'.join(words) if words else '当前规则库未命中字面高风险词；不代表无风险'}。\n"
               f"③违规类型：{'、'.join(types) if types else '暂未形成类型候选'}；平台规则须按实际投放日复核。\n"
               f"④法律依据：{'；'.join(bases) if bases else '未形成自动适用结论'}。\n"
               f"⑤修改建议：{advice}\n"
               f"⑥风险定级：预审{pre_level}、法务推荐{legal_level}；结论待人工复核。")
    permit = next((_text(v) for k, v in payload["extras"].items() if "批准文号" in k or "备案" in k or "版号" in k), "")
    timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
    return {"request_id": payload["record_id"], "resolved_mode": "标准",
            "mode_reason": "MVP阶段统一使用标准审核模式" if payload["mode"] != "标准" else "",
            "预审_风险等级": pre_level, "预审_命中要点": hit_summary, "预审_修改建议": advice,
            "预审_时间": timestamp, "审核_审核意见": opinion,
            "审核_关键实体抽取": "，".join(entities) or "无",
            "审核_高风险词命中": "，".join(words) or "无",
            "审核_备案核查结果": ("已收到备案/批准/版号信息，仅完成字段留痕，真实性、有效性及对应关系待核查" if permit else
                              "未提供可识别的备案/批准/版号信息，形式及实质核查均待接入"),
            "审核_推荐违规类型": types, "审核_推荐风险等级": legal_level,
            "matched_rules": matched, "审核_审核时间": timestamp, "routing": routing,
            "audit_time": timestamp,
            "context_package": {"contract_version": "0.2", "rule_engine": "video_claim_patterns",
                                "content_sha256": hashlib.sha256(payload["content"].encode()).hexdigest(),
                                "human_review_required": True}}


SCENE_RULES = {
    "before_after_comparison": ("ADSURE-SCENE-BEFORE-AFTER", "前后对比画面待核验", "虚假宣传", "运营补资料"),
    "medical_setting": ("ADSURE-SCENE-MEDICAL", "医疗场景关联待核验", "涉医疗宣传", "法务"),
    "third_party_endorsement": ("ADSURE-SCENE-ENDORSEMENT", "第三方背书画面待核验", "广告代言不合规", "法务"),
    "promotional_offer": ("ADSURE-SCENE-PROMOTION", "画面促销承诺待核验", "价格促销误导", "运营补资料"),
    "sexual_or_violent_content": ("ADSURE-SCENE-CONTENT", "画面内容安全待核验", "其他", "法务"),
}
MATERIAL_RULES = {
    "product_claim": ("ADSURE-MATERIAL-CLAIM", "产品主张证明材料待核验", "虚假宣传"),
    "campaign": ("ADSURE-CAMPAIGN-CONDITIONS", "活动条件与兑现材料待核验", "价格促销误导"),
    "landing_page": ("ADSURE-LANDING-CONSISTENCY", "广告与落地页一致性待核验", "其他"),
}


def _stable_rule_uid(rule_id: str) -> str:
    return hashlib.sha256(f"adsure-rule|{rule_id}".encode()).hexdigest()[:24]


def _video_rule(*, rule_id: str, title: str, dimension: str, risk_level: str,
                reason: str, evidence: str, route: str, legal_basis=None,
                missing=None, applicability_reason="") -> dict:
    return {"rule_id": rule_id, "rule_uid": _stable_rule_uid(rule_id), "title": title,
            "dimension": dimension, "risk_level": risk_level,
            "judgment": "视频报告生成风险候选，需结合原视频、语境和事实材料人工判断",
            "match_reason": reason, "default_routing": route,
            "legal_basis": legal_basis or [], "applicability_status": "needs_fact_verification",
            "confidence": None, "material_evidence": evidence,
            "satisfied_elements": ["视频审核报告存在可回溯的机器证据或核验缺口"],
            "unsatisfied_elements": ["尚未完成人工语境、事实及规则适用性核验"],
            "missing_facts": list(dict.fromkeys(missing or ["完整投放语境"])),
            "applicability_reason": applicability_reason or "机器结果不构成违法认定。",
            "serial_no": None}


def build_video_response(report: dict, state: dict, *, now_ms: int | None = None) -> dict:
    """Adapt an immutable video report to the Feishu v0.2 final response."""
    raw_risks = sorted(report.get("risks", []), key=lambda r: (
        {"high": 0, "medium": 1, "low": 2}.get(r.get("severity"), 3), r.get("risk_id", "")))
    matched = []
    types = []
    for risk in raw_risks:
        level = LEVEL.get(risk.get("severity"), "中")
        pattern_id = risk.get("pattern_id", "")
        route = "运营补资料" if pattern_id in FACT_PATTERNS else "法务" if level == "高" else "运营"
        kind = TYPE_MAP.get(risk.get("risk_dimension", ""), "其他")
        types.append(kind)
        missing = ["产品法律属性", "主张对应证明材料"] if pattern_id in FACT_PATTERNS else ["完整视频语境"]
        for rule_id in risk.get("rule_ids", []) or ["ADSURE-VIDEO-RISK"]:
            matched.append(_video_rule(rule_id=rule_id, title=risk.get("title", "视频风险候选"),
                dimension=risk.get("risk_dimension", "其他"), risk_level=level,
                reason=f"{risk.get('source','video')} 在 {float(risk.get('t_start',0)):.2f}–{float(risk.get('t_end',0)):.2f} 秒命中“{risk.get('matched_text','')}”",
                evidence=risk.get("context_text") or risk.get("matched_text", ""), route=route,
                legal_basis=_basis(risk), missing=missing,
                applicability_reason=risk.get("explanation", "机器规则候选，需人工复核。")))

    requirement_gaps = []
    for check in report.get("requirement_checks", []):
        if check.get("status") in {"observed", "observed_in_all_samples"}:
            continue
        requirement_gaps.append(check.get("explanation", "必要展示项需人工复核"))
        for rule_id in check.get("rule_ids", []) or ["ADSURE-VIDEO-DISCLOSURE"]:
            matched.append(_video_rule(rule_id=rule_id, title=check.get("title", "必要展示项待核验"),
                dimension="必要展示项", risk_level="中", reason=check.get("explanation", "覆盖不足"),
                evidence="、".join(check.get("evidence_ids", [])) or "未取得充分画面证据", route="法务",
                missing=["完整视频连续展示情况", "文字清晰度和显著性"],
                applicability_reason="抽帧与 OCR 只能提供采样证据，不能替代逐帧人工确认。"))
        types.append("平台准入/资质不符")

    materials = report.get("material_verification", {})
    material_gaps = []
    for check in materials.get("checks", []):
        if check.get("status") in {"document_consistency_only", "limited_text_consistency_only"}:
            continue
        rule_id, title, kind = MATERIAL_RULES.get(check.get("check_type"),
            ("ADSURE-MATERIAL-REVIEW", "证明材料待核验", "其他"))
        problems = list(dict.fromkeys(check.get("gaps", []) + check.get("conflicts", [])))
        material_gaps.extend(problems)
        reason = f"{check.get('claim','相关主张')}：{check.get('status','review_required')}"
        if problems:
            reason += "；" + "；".join(problems)
        matched.append(_video_rule(rule_id=rule_id, title=title, dimension=title, risk_level="中",
            reason=reason, evidence=check.get("claim", ""), route="运营补资料", missing=problems,
            applicability_reason=check.get("conclusion", "材料存在性不等于真实性和证明力已确认。")))
        types.append(kind)

    for scene in report.get("visual_semantics", {}).get("observations", []):
        definition = SCENE_RULES.get(scene.get("category"))
        if not definition:
            continue
        rule_id, title, kind, route = definition
        frame_ids = "、".join(scene.get("frame_ids", []))
        matched.append(_video_rule(rule_id=rule_id, title=title, dimension=title, risk_level="中",
            reason=f"代表帧 {frame_ids} 在 {float(scene.get('t_start',0)):.2f}–{float(scene.get('t_end',0)):.2f} 秒出现相关画面候选",
            evidence=scene.get("description", ""), route=route,
            missing=[scene.get("uncertainty", "画面含义与真实性需人工核验")],
            applicability_reason="画面语义为模型观察，grounding_status=model_observation_unverified。"))
        types.append(kind)

    matched = _aggregate_matched(matched)
    types = list(dict.fromkeys(types))
    level_rank = {"低": 0, "中": 1, "高": 2}
    highest = max((r["risk_level"] for r in matched), key=level_rank.get, default="低")
    incomplete = report.get("coverage_status") != "sampled_complete" or report.get("analysis_status") != "completed"
    pre_level = highest if matched or incomplete else "无明显风险"
    routing = "法务" if any(r["default_routing"] == "法务" for r in matched) else "运营"
    words = list(dict.fromkeys(r.get("matched_text", "") for r in raw_risks if r.get("matched_text")))
    scope = report.get("scope", {})
    entities = list(dict.fromkeys(filter(None, [scope.get("product_name"), scope.get("product_id"),
        scope.get("product_category"), state.get("platform") or scope.get("platform")])))
    if matched:
        summary = "；".join(r["match_reason"] for r in matched)[:80]
        advice_items = list(dict.fromkeys(r.get("recommendation", "") for r in raw_risks if r.get("recommendation")))
        if material_gaps:
            advice_items.append("补充或更正产品证明、活动条件及落地页材料")
        advice = "；".join(advice_items)[:100] or "结合原视频和所列缺失事实完成人工复核。"
    else:
        summary = ("识别覆盖不足，未命中不代表无风险" if incomplete else
                   "未命中当前规则库的风险候选，不代表无风险；仍需结合完整素材和行业规则人工复核")[:80]
        advice = "复核完整视频、口播、画面、产品材料和平台现行规则后再决定投放。"[:100]

    platform = report.get("platform_verification", {})
    platform_items = [f"{f.get('platform','平台')} {f.get('locator','')}：{f.get('rule_summary','')}（{f.get('review_status','待复核')}）"
                      for f in platform.get("findings", [])]
    platform_text = "；".join(platform_items + platform.get("warnings", [])) or "未形成可用的平台规则预检结果"
    bases = list(dict.fromkeys(x for r in matched for x in r.get("legal_basis", [])))
    warnings = report.get("warnings", [])
    opinion = (f"①风险定性：视频审核生成{len(matched)}项规则或核验候选；覆盖状态为{report.get('coverage_status','unknown')}，不构成违法认定。\n"
               f"②违禁词鉴别：{'、'.join(words) if words else '当前可用文字证据未命中字面高风险词；不代表无风险'}。\n"
               f"③违规类型：{'、'.join(types) if types else '暂未形成类型候选'}。平台预检：{platform_text}\n"
               f"④法律依据：{'；'.join(bases) if bases else '未形成自动适用结论'}。\n"
               f"⑤修改建议：{advice}\n"
               f"⑥风险定级：预审{pre_level}、法务推荐{highest}；{('识别或核验覆盖不足；' if incomplete else '')}结论待人工复核。")
    unreadable = materials.get("unreadable_documents", [])
    if not materials.get("document_count"):
        material_status = "未提交产品证明材料，备案/版号形式及实质核查均待接入"
    elif unreadable:
        material_status = f"已收到{materials.get('document_count')}份材料，其中{len(unreadable)}份提取不完整；官方验真未接入"
    else:
        material_status = f"已收到{materials.get('document_count')}份材料并完成文本一致性检查；真实性、有效性及官方验真未确认"
    timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
    return {"request_id": state.get("request_id") or state.get("record_id") or report.get("job_id", ""),
            "resolved_mode": "标准", "mode_reason": "MVP阶段统一使用标准审核模式" if state.get("mode", "标准") != "标准" else "",
            "预审_风险等级": pre_level, "预审_命中要点": summary, "预审_修改建议": advice,
            "预审_时间": timestamp, "审核_审核意见": opinion,
            "审核_关键实体抽取": "，".join(entities) or "无", "审核_高风险词命中": "，".join(words) or "无",
            "审核_备案核查结果": material_status, "审核_推荐违规类型": types,
            "审核_推荐风险等级": highest, "matched_rules": matched,
            "审核_审核时间": timestamp, "routing": routing, "audit_time": timestamp,
            "审核_平台规则预检": platform_text,
            "context_package": {"contract_version": "0.2", "source": "video_mvp_report_v3",
                "job_id": report.get("job_id"), "coverage_status": report.get("coverage_status"),
                "analysis_status": report.get("analysis_status"),
                "visual_semantics_status": report.get("visual_semantics", {}).get("status"),
                "material_verification_status": materials.get("status"),
                "platform_verification_status": platform.get("status"),
                "warnings_count": len(warnings), "material_gaps": list(dict.fromkeys(material_gaps)),
                "requirement_gaps": list(dict.fromkeys(requirement_gaps)), "human_review_required": True}}
