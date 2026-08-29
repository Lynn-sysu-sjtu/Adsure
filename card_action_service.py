"""Transport-independent service for every Feishu card action."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import time
from typing import Any, Mapping, Optional

from logging_utils import context_fields, mask_identifier
from reliable_queue import ACTIVE_STATUSES, SUCCEEDED, SQLiteQueue, get_store
from user_messages import (
    ACTION_ACCEPTED,
    ACTION_IN_PROGRESS,
    ACTION_RETRY,
    STALE_CARD,
)


logger = logging.getLogger(__name__)
VALID_MODES = {"极速", "标准", "深度"}


@dataclass(frozen=True)
class CardActionRequest:
    action: str
    record_id: str
    operator_id: Optional[str] = None
    event_id: Optional[str] = None
    event_time_ms: Optional[int] = None
    mode: Optional[str] = None
    round: Optional[int] = None
    transport: str = "unknown"


@dataclass(frozen=True)
class CardActionResult:
    message: str
    toast_type: str
    job_id: Optional[int]
    created: bool


def _event_key(request: CardActionRequest, now: Optional[float] = None) -> str:
    if request.event_id:
        raw = f"event:{request.event_id}"
    else:
        current_ms = int((time.time() if now is None else now) * 1000)
        event_ms = int(request.event_time_ms or current_ms)
        five_minute_bucket = event_ms // 300_000
        raw = json.dumps(
            [
                request.action,
                request.record_id,
                request.operator_id or "",
                request.mode or "",
                five_minute_bucket,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        logger.warning(
            "event=card_action_missing_event_id %s",
            context_fields(
                action=request.action,
                record_id=request.record_id,
                transport=request.transport,
            ),
        )
    return "card:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def handle_card_action(
    request: CardActionRequest,
    *,
    store: Optional[SQLiteQueue] = None,
    now: Optional[float] = None,
) -> CardActionResult:
    queue = store or get_store()
    action = (request.action or "").strip()
    record_id = (request.record_id or "").strip()
    if not action or not record_id:
        logger.warning(
            "event=invalid_card_action %s",
            context_fields(
                action=action, record_id=record_id, transport=request.transport
            ),
        )
        return CardActionResult(STALE_CARD, "info", None, False)

    if action == "confirm_mode" and request.mode not in VALID_MODES:
        logger.warning(
            "event=invalid_legacy_mode %s",
            context_fields(
                action=action, record_id=record_id, transport=request.transport
            ),
        )
        return CardActionResult(STALE_CARD, "info", None, False)

    mapping = {
        "start_ai_review": ("context_confirm", {}),
        "confirm_mode": ("ai_review", {"mode": request.mode}),
        "resubmit": ("resubmit", {}),
        "skip_review": ("route_to_legal", {"source": "skip_review"}),
        "escalate_to_legal": ("route_to_legal", {"source": "escalate_to_legal"}),
    }
    selected = mapping.get(action)
    if selected is None:
        logger.warning(
            "event=unknown_card_action %s",
            context_fields(
                action_hash=mask_identifier(action),
                record_id=record_id,
                transport=request.transport,
            ),
        )
        return CardActionResult(STALE_CARD, "info", None, False)

    job_type, extra_payload = selected
    current_round = queue.current_round(record_id)
    if request.round is not None and request.round != current_round:
        logger.info(
            "event=stale_card_round %s",
            context_fields(
                action=action,
                record_id=record_id,
                card_round=request.round,
                current_round=current_round,
            ),
        )
        return CardActionResult(STALE_CARD, "info", None, False)
    if request.round is None:
        if current_round > 1:
            logger.info(
                "event=unversioned_legacy_card_stale %s",
                context_fields(
                    action=action, record_id=record_id, current_round=current_round
                ),
            )
            return CardActionResult(STALE_CARD, "info", None, False)
        try:
            current_status = _legacy_record_status(record_id)
        except Exception:
            logger.exception(
                "event=legacy_card_state_read_failed %s",
                context_fields(action=action, record_id=record_id),
            )
            return CardActionResult(ACTION_RETRY, "error", None, False)
        if current_status not in _allowed_source_statuses(action):
            logger.info(
                "event=stale_legacy_card_ignored %s",
                context_fields(
                    action=action, record_id=record_id, current_status=current_status
                ),
            )
            return CardActionResult(STALE_CARD, "info", None, False)

    event_key = _event_key(request, now=now)
    if action in {"start_ai_review", "skip_review"}:
        business_prefix = "initial-choice"
    elif action == "confirm_mode":
        business_prefix = "mode-confirm"
    elif action == "escalate_to_legal":
        business_prefix = "legal-route"
    else:
        business_prefix = "resubmit"
    idempotency_key = f"{business_prefix}:{record_id}:round:{current_round}"
    payload = {
        "action": action,
        "operator_id": request.operator_id,
        "event_key": event_key,
        "round": current_round,
        **extra_payload,
    }
    try:
        queued = queue.enqueue_job(
            job_type,
            record_id,
            idempotency_key,
            payload,
            max_attempts=_max_job_attempts(),
        )
    except Exception:
        logger.exception(
            "event=card_action_enqueue_failed %s",
            context_fields(
                action=action, record_id=record_id, idempotency_key=idempotency_key
            ),
        )
        return CardActionResult(ACTION_RETRY, "error", None, False)

    if not queued.created:
        if queued.status in ACTIVE_STATUSES:
            message = ACTION_IN_PROGRESS
        elif queued.status == SUCCEEDED:
            message = STALE_CARD
        else:
            message = ACTION_RETRY
        return CardActionResult(
            message,
            "info" if message != ACTION_RETRY else "error",
            queued.item_id,
            False,
        )

    message = ACTION_ACCEPTED
    logger.info(
        "event=card_action_enqueued %s",
        context_fields(
            action=action,
            record_id=record_id,
            job_id=queued.item_id,
            idempotency_key=idempotency_key,
            transport=request.transport,
        ),
    )
    return CardActionResult(message, "success", queued.item_id, True)


def _max_job_attempts() -> int:
    try:
        import config

        return int(getattr(config, "ADSURE_JOB_MAX_ATTEMPTS", 5))
    except ImportError:
        return 5


def _allowed_source_statuses(action: str) -> set[str]:
    if action in {"start_ai_review", "confirm_mode", "skip_review"}:
        return {"运营起草"}
    if action == "escalate_to_legal":
        return {"待运营修改"}
    if action == "resubmit":
        return {"待运营修改", "运营补资料", "需修改"}
    return set()


def _legacy_record_status(record_id: str) -> str:
    import feishu_api
    from fields_v4 import F_流转_当前状态

    fields = feishu_api.get_record(record_id).get("fields", {})
    return str(fields.get(F_流转_当前状态) or "")


def parse_http_action(body: Mapping[str, Any]) -> CardActionRequest:
    event = body.get("event") if isinstance(body.get("event"), Mapping) else {}
    action_obj = (
        event.get("action")
        if isinstance(event.get("action"), Mapping)
        else body.get("action", {})
    )
    if not isinstance(action_obj, Mapping):
        action_obj = {}
    value = (
        action_obj.get("value") if isinstance(action_obj.get("value"), Mapping) else {}
    )
    header = body.get("header") if isinstance(body.get("header"), Mapping) else {}
    operator = (
        event.get("operator")
        if isinstance(event.get("operator"), Mapping)
        else body.get("operator", {})
    )
    if not isinstance(operator, Mapping):
        operator = {}
    operator_id = (
        operator.get("open_id") or (operator.get("operator_id") or {}).get("open_id")
        if isinstance(operator.get("operator_id"), Mapping)
        else operator.get("open_id")
    )
    event_time = (
        header.get("create_time") or body.get("create_time") or event.get("create_time")
    )
    try:
        event_time_ms = int(event_time) if event_time else None
    except (TypeError, ValueError):
        event_time_ms = None
    return CardActionRequest(
        action=str(value.get("action", "")),
        record_id=str(value.get("record_id", "")),
        operator_id=str(operator_id) if operator_id else None,
        event_id=str(
            header.get("event_id")
            or body.get("event_id")
            or event.get("event_id")
            or ""
        )
        or None,
        event_time_ms=event_time_ms,
        mode=str(value.get("mode", "")) or None,
        round=_optional_int(value.get("round")),
        transport="http",
    )


def _optional_int(value) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
