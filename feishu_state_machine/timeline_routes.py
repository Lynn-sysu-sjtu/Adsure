"""HTTP adapter for the optional ordinary-user audit timeline."""

from __future__ import annotations

import logging

from audit_service import public_timeline
from feature_flags import audit_timeline_enabled
from logging_utils import context_fields


logger = logging.getLogger(__name__)


def register_timeline_routes(app) -> None:
    app.route("/api/records/<record_id>/timeline")(get_record_timeline)
    context_processor = getattr(app, "context_processor", None)
    if context_processor:
        context_processor(timeline_template_context)


def timeline_template_context() -> dict:
    return {"audit_timeline_available": audit_timeline_enabled()}


def get_record_timeline(record_id: str):
    if not audit_timeline_enabled():
        return "", 404
    try:
        return _jsonify({"events": public_timeline(record_id)})
    except Exception:
        logger.exception(
            "event=timeline_load_failed %s", context_fields(record_id=record_id)
        )
        return _jsonify(
            {"events": [], "message": "暂未显示"}
        ), 503


def _jsonify(payload: dict):
    from flask import jsonify

    return jsonify(payload)
