"""Optional append-only business audit events and public timeline formatting."""

from __future__ import annotations

import datetime
from typing import Optional

from audit_event_writer import (
    INTERNAL_EVENT_TYPES,
    append_event,
    record_internal_event,
)
from feature_flags import audit_timeline_enabled
from reliable_queue import SQLiteQueue, get_store

PUBLIC_EVENT_TYPES = {
    "material_submitted",
    "ai_review_requested",
    "ai_review_started",
    "ai_review_completed",
    "material_resubmitted",
    "routed_to_legal",
    "legal_review_completed",
}


def record_event(
    event_type: str,
    *,
    record_id: str,
    event_key: str,
    summary: Optional[dict] = None,
    actor_role: str = "system",
    actor_name: str = "",
    job_id: Optional[int] = None,
    delivery_id: Optional[int] = None,
    store: Optional[SQLiteQueue] = None,
    internal: bool = False,
) -> bool:
    """Append one event when enabled; failures never affect the business flow."""
    kwargs = {
        "record_id": record_id,
        "event_key": event_key,
        "summary": summary,
        "actor_role": actor_role,
        "actor_name": actor_name,
        "job_id": job_id,
        "delivery_id": delivery_id,
        "store": store,
    }
    if internal:
        return record_internal_event(event_type, **kwargs)
    if not audit_timeline_enabled() or event_type not in PUBLIC_EVENT_TYPES:
        return False
    return append_event(event_type, **kwargs)


def public_timeline(
    record_id: str, *, store: Optional[SQLiteQueue] = None
) -> list[dict]:
    """Return only allowlisted, human-readable fields for the ordinary UI."""
    rows = (store or get_store()).list_audit_events(record_id)
    events = []
    for row in rows:
        event_type = row.get("event_type")
        if event_type not in PUBLIC_EVENT_TYPES:
            continue
        title, detail = _public_copy(event_type, row.get("summary") or {})
        events.append(
            {
                "time": _format_time(row.get("created_at")),
                "title": title,
                "detail": detail,
            }
        )
    return events


def _public_copy(event_type: str, summary: dict) -> tuple[str, str]:
    round_number = summary.get("round")
    round_text = f"第 {round_number} 轮" if isinstance(round_number, int) else ""
    if event_type == "material_submitted":
        return "物料已提交", round_text
    if event_type == "ai_review_requested":
        return "已发起 AI 审核", round_text
    if event_type == "ai_review_started":
        mode = summary.get("mode")
        return "AI 审核已开始", (
            f"{mode}模式" if mode in {"极速", "标准", "深度"} else round_text
        )
    if event_type == "ai_review_completed":
        risk = str(summary.get("risk_level") or "")
        detail = f"风险等级：{risk}" if risk else round_text
        return "AI 审核已完成", detail
    if event_type == "material_resubmitted":
        return "物料已重新提交", round_text
    if event_type == "routed_to_legal":
        source = {
            "skip_review": "运营选择跳过 AI",
            "escalate_to_legal": "运营主动转交",
            "ai_review": "AI 审核结果",
        }.get(summary.get("source"), "")
        return "已进入法务复核流程", source or round_text
    if event_type == "legal_review_completed":
        verdict = summary.get("verdict")
        reviewer = str(summary.get("reviewer_name") or "")
        detail_parts = []
        if reviewer:
            detail_parts.append(f"审核人：{reviewer}")
        if verdict in {"通过", "不通过"}:
            detail_parts.append(f"裁决：{verdict}")
        title = "法务裁决已更新" if summary.get("is_edit") is True else "法务审核已完成"
        return title, "；".join(detail_parts)
    return "审核进度已更新", ""


def _format_time(raw) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(raw)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""
