"""HTTP routes for the optional compliance-memory switch."""

from __future__ import annotations

import logging

import memory_center


logger = logging.getLogger(__name__)

SWITCH_FAILED = "暂时未能切换，请稍后再试"
SETTINGS_UNAVAILABLE = "暂时未能读取设置，请稍后刷新"
_REQUEST_DATA_MISSING = object()


def register_memory_routes(app) -> None:
    """Register thin routes without requiring a Blueprint or a new process."""
    app.route("/api/memory-center/settings", methods=["GET"])(get_memory_settings)
    app.route("/api/memory-center/settings", methods=["POST"])(post_memory_settings)
    context_processor = getattr(app, "context_processor", None)
    if context_processor:
        context_processor(memory_template_context)


def memory_template_context() -> dict:
    return {"memory_center_available": memory_center.available()}


def get_memory_settings():
    if not memory_center.available():
        return "", 404
    try:
        return {"enabled": memory_center.read_enabled()}, 200
    except memory_center.MemoryCenterUnavailable:
        return "", 404
    except Exception:
        logger.warning(
            "event=memory_settings_read_failed error_category=noncritical_persistence"
        )
        return {"success": False, "message": SETTINGS_UNAVAILABLE}, 503


def post_memory_settings(data=_REQUEST_DATA_MISSING):
    if not memory_center.available():
        return "", 404
    try:
        if data is _REQUEST_DATA_MISSING:
            from flask import request

            data = request.get_json(silent=True)
        enabled = data.get("enabled") if isinstance(data, dict) else None
        if type(enabled) is not bool:
            return {"success": False, "message": SWITCH_FAILED}, 400
        memory_center.set_enabled(enabled)
        logger.info("event=memory_setting_updated enabled=%s", str(enabled).lower())
        return {"success": True, "enabled": enabled}, 200
    except memory_center.MemoryCenterUnavailable:
        return "", 404
    except Exception:
        logger.warning(
            "event=memory_setting_update_failed error_category=noncritical_persistence"
        )
        return {"success": False, "message": SWITCH_FAILED}, 503
