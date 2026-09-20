"""Feishu WebSocket transport adapter for the shared card action service."""

from __future__ import annotations

import fcntl
import json
import logging
from typing import Optional

import lark_oapi as lark
import requests
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackToast,
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from card_action_service import CardActionRequest, handle_card_action as handle_action
from config import FEISHU_APP_ID, FEISHU_APP_SECRET
from feishu_api import BASE_URL, get_tenant_access_token
from logging_utils import configure_logging, context_fields, mask_identifier
from user_messages import ACTION_RETRY


logger = logging.getLogger(__name__)
_LOCK_FILE = "/tmp/adsure_bot_listener.lock"
_SECRET_COMMAND = "/adsure secret"


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
        event_time = getattr(header, "create_time", None) or getattr(
            event, "create_time", None
        )
        try:
            event_time_ms: Optional[int] = int(event_time) if event_time else None
        except (TypeError, ValueError):
            event_time_ms = None
        try:
            card_round: Optional[int] = (
                int(value.get("round"))
                if value.get("round") not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            card_round = None

        result = handle_action(
            CardActionRequest(
                action=str(value.get("action", "")),
                record_id=str(value.get("record_id", "")),
                operator_id=str(operator_id) if operator_id else None,
                event_id=str(event_id) if event_id else None,
                event_time_ms=event_time_ms,
                mode=str(value.get("mode", "")) or None,
                round=card_round,
                transport="websocket",
            )
        )
        toast = CallBackToast()
        toast.type = result.toast_type
        toast.content = result.message
        response.toast = toast
    except Exception:
        logger.exception(
            "event=websocket_callback_failed error_category=callback_processing"
        )
        toast = CallBackToast()
        toast.type = "error"
        toast.content = ACTION_RETRY
        response.toast = toast
    return response


def _send_text(open_id: str, text: str) -> None:
    token = get_tenant_access_token()
    resp = requests.post(
        f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": open_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
        timeout=8,
    )
    data = resp.json() if resp.content else {}
    if data.get("code", -1) != 0:
        logger.warning("event=secret_reply_failed code=%s", data.get("code"))


def handle_message_receive(data) -> None:
    try:
        event = getattr(data, "event", None)
        message = getattr(event, "message", None)
        if getattr(message, "chat_type", None) != "p2p":
            return

        raw = getattr(message, "content", "") or ""
        try:
            text = str(json.loads(raw).get("text", "")).strip()
        except Exception:
            return

        if text != _SECRET_COMMAND:
            return

        sender_id = getattr(
            getattr(getattr(event, "sender", None), "sender_id", None), "open_id", None
        )
        if not sender_id:
            return

        try:
            import config as _cfg

            password = str(getattr(_cfg, "ADSURE_OPS_PASSWORD", "") or "")
        except ImportError:
            password = ""

        reply = (
            "🔐 卡片管理后台登录信息\n"
            f"地址：工作台右上角「📦 卡片管理后台」\n"
            f"用户名：adsure_ops\n"
            f"密码：{password or '（未配置）'}"
        )
        _send_text(sender_id, reply)
        logger.info("event=secret_sent open_id=%s", mask_identifier(sender_id))
    except Exception:
        logger.exception(
            "event=message_receive_handler_failed error_category=noncritical"
        )


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
        .register_p2_im_message_receive_v1(handle_message_receive)
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
