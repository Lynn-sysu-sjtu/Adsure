"""Pure legal-review validation and six-combination field semantics."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fields_v4 import (
    F_审核_审核意见,
    F_法务_AI意见评价, F_法务_物料裁决, F_法务_异议字段,
    F_法务_补充或驳回理由, F_法务_驳回正确判定, F_法务_最终修改意见,
    F_法务_批注, F_法务_复核人, F_法务_复核时间,
    F_流转_当前状态, F_流转_反馈类型, F_流转_驳回次数,
)
from user_messages import required_field


VALID_AI_OPINIONS = {"同意无补充", "同意有补充", "驳回"}
VALID_VERDICTS = {"通过", "不通过"}
VALID_REVIEW_INTENTS = {"initial", "edit"}
_VERSION_FIELDS = (
    F_流转_当前状态,
    F_审核_审核意见,
    F_法务_AI意见评价,
    F_法务_物料裁决,
    F_流转_反馈类型,
    F_法务_复核时间,
    F_法务_异议字段,
    F_法务_补充或驳回理由,
    F_法务_驳回正确判定,
    F_法务_最终修改意见,
    F_法务_批注,
    F_法务_复核人,
    F_流转_驳回次数,
)


def validate_review_payload(data: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not str(data.get("reviewer_name", "")).strip():
        errors["reviewer_name"] = required_field("法务审核人")
    opinion = data.get("ai_opinion", "")
    verdict = data.get("verdict", "")
    if opinion not in VALID_AI_OPINIONS:
        errors["ai_opinion"] = required_field("AI意见评价")
    if verdict not in VALID_VERDICTS:
        errors["verdict"] = required_field("物料裁决")
    if opinion == "同意有补充" and not str(data.get("supplement_reason", "")).strip():
        errors["supplement_reason"] = required_field("补充意见")
    if opinion == "驳回":
        if not data.get("objection_fields"):
            errors["objection_fields"] = required_field("异议字段")
        if not str(data.get("reject_reason", "")).strip():
            errors["reject_reason"] = required_field("驳回理由")
        if not str(data.get("correct_judgment", "")).strip():
            errors["correct_judgment"] = required_field("正确判定")
    if verdict == "不通过" and not str(data.get("final_suggestion", "")).strip():
        errors["final_suggestion"] = required_field("最终修改意见")
    intent = data.get("review_intent")
    expected_version = data.get("expected_review_version")
    if intent is not None or expected_version is not None:
        if intent not in VALID_REVIEW_INTENTS:
            errors["review_intent"] = "暂时无法处理"
        if (
            not isinstance(expected_version, str)
            or len(expected_version) != 64
            or any(char not in "0123456789abcdef" for char in expected_version)
        ):
            errors["expected_review_version"] = "暂时无法处理"
    return errors


def review_version(current_fields: dict) -> str:
    """Build an opaque version from fields that affect a legal decision."""
    snapshot = {
        field: _canonical_value(current_fields.get(field)) for field in _VERSION_FIELDS
    }
    encoded = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def review_may_apply(current_fields: dict, data: dict) -> bool:
    """Keep old callers compatible while protecting versioned browser submits."""
    expected = data.get("expected_review_version")
    if expected is None:
        return True
    intent = data.get("review_intent")
    status = current_fields.get(F_流转_当前状态, "")
    allowed_status = (
        status == "待法务复核"
        if intent == "initial"
        else status in {"已通过", "需修改"} if intent == "edit" else False
    )
    return allowed_status and expected == review_version(current_fields)


def _canonical_value(value):
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def review_outcome(data: dict) -> tuple[str, str]:
    status = "已通过" if data.get("verdict") == "通过" else "需修改"
    feedback = {
        "同意无补充": "无",
        "同意有补充": "refine",
        "驳回": "override",
    }[data["ai_opinion"]]
    return status, feedback


def build_update_fields(data: dict, current_fields: dict) -> dict:
    status, feedback = review_outcome(data)
    update = {
        F_法务_AI意见评价: data["ai_opinion"],
        F_法务_物料裁决: data["verdict"],
        F_流转_当前状态: status,
        F_流转_反馈类型: feedback,
        F_法务_复核时间: int(data["submitted_at_ms"]),
    }

    note = _review_note(data)
    if note:
        update[F_法务_批注] = note

    objection = data.get("objection_fields") or []
    if objection:
        update[F_法务_异议字段] = list(objection)

    reason = str(data.get("reject_reason") or data.get("supplement_reason") or "").strip()
    if reason:
        update[F_法务_补充或驳回理由] = reason

    correct = str(data.get("correct_judgment") or "").strip()
    if correct:
        update[F_法务_驳回正确判定] = correct

    suggestion = str(data.get("final_suggestion") or "").strip()
    if suggestion:
        update[F_法务_最终修改意见] = suggestion

    if data.get("ai_opinion") == "驳回":
        old = current_fields.get(F_流转_驳回次数) or 0
        try:
            old = int(old)
        except (TypeError, ValueError):
            old = 0
        update[F_流转_驳回次数] = old + 1
    return update


def record_matches_review(current_fields: dict, data: dict) -> bool:
    """Confirm a possibly timed-out update before retrying it."""
    status, feedback = review_outcome(data)
    expected = {
        F_法务_AI意见评价: data["ai_opinion"],
        F_法务_物料裁决: data["verdict"],
        F_流转_当前状态: status,
        F_流转_反馈类型: feedback,
        F_法务_复核时间: int(data["submitted_at_ms"]),
    }
    for field, value in expected.items():
        if current_fields.get(field) != value:
            return False

    requested_reason = str(data.get("reject_reason") or data.get("supplement_reason") or "").strip()
    if requested_reason and current_fields.get(F_法务_补充或驳回理由) != requested_reason:
        return False
    requested_correct = str(data.get("correct_judgment") or "").strip()
    if requested_correct and current_fields.get(F_法务_驳回正确判定) != requested_correct:
        return False
    requested_suggestion = str(data.get("final_suggestion") or "").strip()
    if requested_suggestion and current_fields.get(F_法务_最终修改意见) != requested_suggestion:
        return False
    requested_objections = list(data.get("objection_fields") or [])
    if requested_objections and list(current_fields.get(F_法务_异议字段) or []) != requested_objections:
        return False
    requested_note = _review_note(data)
    if requested_note and current_fields.get(F_法务_批注) != requested_note:
        return False
    return True


def _review_note(data: dict) -> str:
    reviewer_name = str(data.get("reviewer_name", "")).strip()
    note = str(data.get("note") or "").strip()
    if reviewer_name:
        note = f"【法务：{reviewer_name}】" + (f"\n{note}" if note else "")
    return note


def public_result(data: dict) -> dict[str, Any]:
    status, feedback = review_outcome(data)
    return {
        "success": True,
        "status": status,
        "feedback_type": feedback,
        "notification_pending": bool(data.get("notify_operator", True)),
    }
