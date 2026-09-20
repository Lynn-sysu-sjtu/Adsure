"""Maintenance-only delivery listing and safe same-row replay rules."""

from __future__ import annotations

import datetime
import logging
import math

from audit_event_writer import record_internal_event
from logging_utils import context_fields, mask_identifier
from reliable_queue import SQLiteQueue


logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "pending",
    "running",
    "retryable_failed",
    "succeeded",
    "terminal_failed",
}
VALID_CARD_TYPES = {
    "initial_review",
    "operator_result",
    "operator_more_info",
    "legal_review",
    "operator_transferred",
    "verdict",
    "final_failure",
    "legal_card_update",
}

_STATUS_LABELS = {
    "pending": "待发送",
    "running": "发送中",
    "retryable_failed": "等待再次发送",
    "succeeded": "已发送",
    "terminal_failed": "发送未完成",
}
_CARD_LABELS = {
    "initial_review": "运营初始卡",
    "operator_result": "运营审核结果卡",
    "operator_more_info": "运营补资料卡",
    "legal_review": "法务复核卡",
    "operator_transferred": "法务流转通知卡",
    "verdict": "法务裁决结果卡",
    "final_failure": "处理未完成提示卡",
    "legal_card_update": "法务卡片完成更新",
}
_BUSINESS_LABELS = {
    "initial_review_card": "运营提交审核",
    "review_result": "反馈 AI 审核结果",
    "request_more_info": "请求补充物料",
    "legal_review_notification": "发起法务复核",
    "legal_handoff_accepted": "确认法务流转",
    "legal_verdict_notification": "通知法务裁决",
    "review_terminal_failure": "提示重新操作",
    "legal_card_completed_update": "同步法务完成状态",
}
_ISSUE_LABELS = {
    "rate_limited": "发送频率暂时受限",
    "transient_network": "暂时未送达",
    "permission_denied": "发送权限不可用",
    "invalid_recipient": "接收人不可用",
    "invalid_card": "卡片内容未能发送",
    "worker_interrupted": "发送曾被中断",
    "engine_unavailable": "暂时未送达",
    "data_validation": "卡片暂时无法发送",
}


def list_deliveries(
    store: SQLiteQueue,
    *,
    page=1,
    page_size=20,
    status="",
    card_type="",
    record_query="",
) -> dict:
    page_number = _bounded_int(page, default=1, minimum=1, maximum=1_000_000)
    per_page = _bounded_int(page_size, default=20, minimum=1, maximum=100)
    selected_status = str(status or "")
    selected_card = str(card_type or "")
    if selected_status not in VALID_STATUSES:
        selected_status = ""
    if selected_card not in VALID_CARD_TYPES:
        selected_card = ""
    record_text = str(record_query or "").strip()[:120]
    rows, total = store.list_delivery_summaries(
        page=page_number,
        page_size=per_page,
        status=selected_status,
        card_type=selected_card,
        record_query=record_text,
    )
    return {
        "items": [_public_row(row) for row in rows],
        "page": page_number,
        "page_size": per_page,
        "total": total,
        "total_pages": max(1, math.ceil(total / per_page)),
    }


def replay_delivery(store: SQLiteQueue, delivery_id: int) -> dict:
    try:
        result = store.replay_terminal_delivery(int(delivery_id))
    except (TypeError, ValueError):
        return {"result": "unavailable", "message": "暂时无法处理"}
    except Exception:
        logger.exception("event=ops_delivery_replay_failed")
        return {"result": "unavailable", "message": "暂时无法处理"}

    if result.get("outcome") == "replayed":
        replay_count = int(result["replay_count"])
        record_internal_event(
            "delivery_replayed",
            record_id=result["record_id"],
            event_key=f"delivery_replayed:{int(delivery_id)}:{replay_count}",
            summary={"count": replay_count},
            delivery_id=int(delivery_id),
            store=store,
        )
        logger.info(
            "event=ops_delivery_replayed %s",
            context_fields(
                delivery_id=int(delivery_id),
                record_id=result["record_id"],
                replay_count=replay_count,
            ),
        )
        return {"result": "replayed", "message": "已重新安排发送"}
    if result.get("outcome") == "updated":
        return {"result": "updated", "message": "状态已更新，请刷新查看"}
    return {"result": "unavailable", "message": "暂时无法处理"}


def _public_row(row: dict) -> dict:
    status = str(row.get("status") or "")
    message_id = row.get("message_id")
    return {
        "delivery_id": int(row["id"]),
        "record_id": str(row.get("record_id") or ""),
        "business_type": _BUSINESS_LABELS.get(row.get("business_action"), "卡片投递"),
        "card_type": _CARD_LABELS.get(row.get("card_type"), "其他业务卡片"),
        "recipient": mask_identifier(row.get("recipient_id")),
        "status": _STATUS_LABELS.get(status, "状态未知"),
        "attempts": int(row.get("attempts") or 0),
        "max_attempts": int(row.get("max_attempts") or 0),
        "created_at": _format_time(row.get("created_at")),
        "updated_at": _format_time(row.get("updated_at")),
        "issue": _issue_text(status, row.get("error_category")),
        "message": _mask_message(message_id),
        "can_replay": status == "terminal_failed" and not message_id,
    }


def _issue_text(status: str, category) -> str:
    if status not in {"retryable_failed", "terminal_failed"}:
        return "—"
    return _ISSUE_LABELS.get(str(category or ""), "发送未完成")


def _mask_message(value) -> str:
    masked = mask_identifier(value)
    return "—" if masked == "-" else masked.replace("id#", "msg#", 1)


def _format_time(value) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(value)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return "—"


def _bounded_int(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))
