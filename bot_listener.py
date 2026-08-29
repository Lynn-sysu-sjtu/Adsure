"""Feishu WebSocket transport adapter for the shared card action service."""

from __future__ import annotations

import fcntl
import logging
from typing import Optional

import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackToast,
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from card_action_service import CardActionRequest, handle_card_action as handle_action
from config import FEISHU_APP_ID, FEISHU_APP_SECRET
from logging_utils import configure_logging, context_fields, mask_identifier
from user_messages import ACTION_RETRY


logger = logging.getLogger(__name__)
_LOCK_FILE = "/tmp/adsure_bot_listener.lock"


def handle_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    response = P2CardActionTriggerResponse()
    try:
        event = getattr(data, "event", None)
        action_obj = getattr(event, "action", None)
        value = getattr(action_obj, "value", None) or {}
        operator = getattr(event, "operator", None)
        operator_id = getattr(operator, "open_id", None)
        header = getattr(data, "header", None)
        event_id = getattr(header, "event_id", None) or getattr(event, "event_id", None)
        event_time = getattr(header, "create_time", None) or getattr(event, "create_time", None)
        try:
            event_time_ms: Optional[int] = int(event_time) if event_time else None
        except (TypeError, ValueError):
            event_time_ms = None
        try:
            card_round: Optional[int] = int(value.get("round")) if value.get("round") not in (None, "") else None
        except (TypeError, ValueError):
            card_round = None

        result = handle_action(CardActionRequest(
            action=str(value.get("action", "")),
            record_id=str(value.get("record_id", "")),
            operator_id=str(operator_id) if operator_id else None,
            event_id=str(event_id) if event_id else None,
            event_time_ms=event_time_ms,
            mode=str(value.get("mode", "")) or None,
            round=card_round,
            transport="websocket",
        ))
        toast = CallBackToast()
        toast.type = result.toast_type
        toast.content = result.message
        response.toast = toast
    except Exception:
        logger.exception("event=websocket_callback_failed error_category=callback_processing")
        toast = CallBackToast()
        toast.type = "error"
        toast.content = ACTION_RETRY
        response.toast = toast
    return response


def main():
    configure_logging()
    lock_fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("event=bot_listener_already_running")
        lock_fd.close()
        return

    logger.info("event=bot_listener_started app_id=%s", mask_identifier(FEISHU_APP_ID))
    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(handle_card_action)
        .build()
    )
    client = lark.ws.Client(
        app_id=FEISHU_APP_ID,
        app_secret=FEISHU_APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    try:
        client.start()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
