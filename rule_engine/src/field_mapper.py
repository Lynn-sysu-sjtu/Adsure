# -*- coding: utf-8 -*-
"""Map Feishu bitable records into the rule engine audit request shape."""

import re


PUBLIC_FIELDS = {
    "material_id": "①运营·物料编号",
    "industry": "①运营·行业领域",
    "content": "①运营·物料内容",
    "attachments": "①运营·物料附件",
    "submitter": "①运营·提交人",
    "submitted_at": "①运营·提交时间",
    "urgency": "①运营·紧急程度",
    "supplemental_background": "①运营·补充背景资料",
}

INDUSTRY_FIELDS = {
    "美妆": {
        "material_type": "①美妆·物料类型",
        "platforms": "①美妆·投放平台",
        "product_category": "①美妆·产品品类",
        "product_filing_name": "①美妆·产品备案名称",
        "scenario": "①美妆·物料涉及场景",
        "core_claims": "①美妆·核心宣称功效",
    },
    "保健食品": {
        "material_type": "①保健食品·物料类型",
        "platforms": "①保健食品·投放平台",
        "product_category": "①保健食品·产品品类",
        "scenario": "①保健食品·物料涉及场景",
        "core_claims": "①保健食品·核心宣称功效",
        "product_filing_name": "①保健食品·产品备案名称",
        "approval_or_filing_number": "①保健食品·批准文号",
    },
    "游戏": {
        "material_type": "①游戏·物料类型",
        "platforms": "①游戏·投放平台",
        "product_category": "①游戏·产品品类",
        "game_name": "①游戏·游戏名称",
        "scenario": "①游戏·物料涉及场景",
        "ip_name": "①游戏·IP名称",
    },
}

MATERIAL_TYPE_NORMALIZATION = {
    "图文": "图文文案",
    "短视频": "短视频脚本",
    "Banner": "Banner文字",
    "详情页": "详情页文字",
    "直播话术": "直播话术",
    "其他": "其他文字材料",
}



def _plain_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "".join(_plain_text(item) for item in value).strip()
    if isinstance(value, dict):
        if "text" in value:
            return _plain_text(value.get("text"))
        if "name" in value:
            return _plain_text(value.get("name"))
        if "id" in value:
            return _plain_text(value.get("id"))
    return str(value).strip()


def _list_value(value):
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items = value
    else:
        items = re.split(r"[,，、\n]+", str(value))
    return [_plain_text(item) for item in items if _plain_text(item)]


def _field(fields, name):
    return fields.get(name)


def _normalize_material_type(value):
    text = _plain_text(value)
    return MATERIAL_TYPE_NORMALIZATION.get(text, text)


def _flat_payload_to_fields(payload):
    """Convert teammate's compact Feishu callback shape to Chinese field keys."""
    if "fields" in payload or "record" in payload:
        return None
    if not any(key in payload for key in ("industry", "content", "platform", "extras")):
        return None

    industry = _plain_text(payload.get("industry"))
    industry_map = INDUSTRY_FIELDS.get(industry, {})
    fields = {
        PUBLIC_FIELDS["material_id"]: payload.get("material_id") or payload.get("record_id"),
        PUBLIC_FIELDS["industry"]: industry,
        PUBLIC_FIELDS["content"]: payload.get("content"),
        PUBLIC_FIELDS["urgency"]: payload.get("urgency"),
        PUBLIC_FIELDS["supplemental_background"]: payload.get("supplement"),
    }

    if industry_map:
        fields[industry_map["material_type"]] = payload.get("material_type")
        fields[industry_map["platforms"]] = payload.get("platform")
        fields[industry_map["product_category"]] = payload.get("product_category")
        fields[industry_map["scenario"]] = payload.get("scenario")

    extras = payload.get("extras") or {}
    if industry_map:
        extra_mapping = {
            "产品备案名称": "product_filing_name",
            "核心宣称功效": "core_claims",
            "批准文号": "approval_or_filing_number",
            "游戏名称": "game_name",
            "IP名称": "ip_name",
            "物料涉及场景": "scenario",
        }
        for extra_key, internal_key in extra_mapping.items():
            field_name = industry_map.get(internal_key)
            if field_name:
                fields[field_name] = extras.get(extra_key)
    return fields


def map_feishu_payload(payload):
    """Normalize a Feishu callback payload into the internal audit request."""
    fields = (
        payload.get("fields")
        or payload.get("record", {}).get("fields")
        or _flat_payload_to_fields(payload)
        or payload
    )
    record_id = payload.get("record_id") or payload.get("record", {}).get("record_id") or fields.get("record_id")

    industry = _plain_text(_field(fields, PUBLIC_FIELDS["industry"]))
    industry_map = INDUSTRY_FIELDS.get(industry, {})

    context = {
        "industry": industry,
        "material_type": _normalize_material_type(_field(fields, industry_map.get("material_type", ""))),
        "platforms": _list_value(_field(fields, industry_map.get("platforms", ""))),
        "product_category": _plain_text(_field(fields, industry_map.get("product_category", ""))),
        "product_filing_name": _plain_text(_field(fields, industry_map.get("product_filing_name", ""))),
        "approval_or_filing_number": _plain_text(_field(fields, industry_map.get("approval_or_filing_number", ""))),
        "core_claims": _list_value(_field(fields, industry_map.get("core_claims", ""))),
        "scenario": _plain_text(_field(fields, industry_map.get("scenario", ""))),
        "game_name": _plain_text(_field(fields, industry_map.get("game_name", ""))),
        "ip_name": _plain_text(_field(fields, industry_map.get("ip_name", ""))),
    }

    return {
        "request_id": record_id or _plain_text(_field(fields, PUBLIC_FIELDS["material_id"])),
        "source": "feishu",
        "material": {
            "material_id": _plain_text(_field(fields, PUBLIC_FIELDS["material_id"])),
            "content": _plain_text(_field(fields, PUBLIC_FIELDS["content"])),
            "attachments": _field(fields, PUBLIC_FIELDS["attachments"]) or [],
            "submitter": _plain_text(_field(fields, PUBLIC_FIELDS["submitter"])),
            "submitted_at": _field(fields, PUBLIC_FIELDS["submitted_at"]),
            "urgency": _plain_text(_field(fields, PUBLIC_FIELDS["urgency"])),
            "supplemental_background": _plain_text(_field(fields, PUBLIC_FIELDS["supplemental_background"])),
        },
        "context": context,
        "audit": {
            "requested_mode": payload.get("mode") or payload.get("requested_mode") or "auto",
        },
        "raw": {
            "record_id": record_id,
            "fields": fields,
        },
    }

