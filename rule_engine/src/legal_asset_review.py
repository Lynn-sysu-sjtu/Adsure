# -*- coding: utf-8 -*-
"""V2 quality checks: only core evidence may authorize proactive topics."""

import json

from legal_asset_review_v1 import *  # noqa: F401,F403
from legal_asset_review_v1 import DOMAIN_MARKERS, export_review_workbook


def _text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _core_rule_text(rule):
    return _text({
        "title": rule.get("title"),
        "legal_basis": rule.get("legal_basis"),
        "applies_to": rule.get("applies_to"),
        "rule_applicability": rule.get("rule_applicability"),
        "source_type": rule.get("source_type"),
        "platform": rule.get("platform"),
    })


def assess_candidate_quality(issue_asset, mapping_asset, check_asset, records_by_uid):
    warnings = []
    for issue in issue_asset.get("issues") or []:
        if issue.get("track") == "通用" or str(issue.get("issue_id") or "").startswith("GEN."):
            for uid in issue.get("candidate_rule_uids") or []:
                record = records_by_uid.get(uid) or {}
                if record.get("track") in {"游戏", "美妆", "保健食品"}:
                    warnings.append({"severity": "warning", "code": "TRACK_RULE_MAPPED_TO_GEN", "record_id": issue.get("issue_id"), "rule_uid": uid, "message": f"{record.get('track')}目录规则被映射为通用问题，需人工确认是否确属跨赛道规则。"})
    for check in check_asset.get("checks") or []:
        check_text = _text({"name": check.get("name"), "requirement": check.get("requirement"), "required_materials": check.get("required_materials")})
        for uid in check.get("basis_rule_uids") or []:
            record = records_by_uid.get(uid) or {}
            core_text = _core_rule_text(record.get("rule") or {})
            unsupported = [marker for marker in DOMAIN_MARKERS if marker in check_text and marker not in core_text]
            if unsupported:
                warnings.append({"severity": "high", "code": "UNSUPPORTED_PROACTIVE_TOPIC", "record_id": check.get("check_id"), "rule_uid": uid, "message": "主动核查出现未被核心依据直接支持的主题：" + "、".join(unsupported)})
    return warnings
