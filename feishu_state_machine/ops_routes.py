"""Thin HTTP routes for the disabled-by-default delivery operations center."""

from __future__ import annotations

import logging
import secrets

from ops_delivery_service import list_deliveries, replay_delivery
from reliable_queue import get_store


logger = logging.getLogger(__name__)


def register_ops_routes(app) -> None:
    app.route("/ops/deliveries")(ops_deliveries_page)
    app.route("/api/ops/deliveries")(ops_delivery_list)
    app.route("/api/ops/deliveries/<int:delivery_id>/replay", methods=["POST"])(
        ops_delivery_replay
    )
    context_processor = getattr(app, "context_processor", None)
    if context_processor:
        context_processor(_ops_template_context)


def _ops_template_context() -> dict:
    return {"ops_enabled": _settings() is not None}


def ops_deliveries_page():
    settings = _settings()
    if settings is None:
        return "", 404
    if not _authorized(settings):
        return _unauthorized()
    return _render_template("ops_deliveries.html")


def ops_delivery_list():
    settings = _settings()
    if settings is None:
        return "", 404
    if not _authorized(settings):
        return _unauthorized()
    args = _request().args
    try:
        result = list_deliveries(
            get_store(),
            page=args.get("page", 1),
            page_size=args.get("page_size", 20),
            status=args.get("status", ""),
            card_type=args.get("card_type", ""),
            record_query=args.get("record", ""),
        )
        return _jsonify(result)
    except Exception:
        logger.exception("event=ops_delivery_list_failed")
        return _jsonify({"items": [], "message": "暂时无法处理"}), 503


def ops_delivery_replay(delivery_id: int):
    settings = _settings()
    if settings is None:
        return "", 404
    if not _authorized(settings):
        return _unauthorized()
    try:
        return _jsonify(replay_delivery(get_store(), delivery_id))
    except Exception:
        logger.exception("event=ops_delivery_replay_route_failed")
        return _jsonify({"result": "unavailable", "message": "暂时无法处理"}), 503


def _settings():
    try:
        import config
    except ImportError:
        return None
    if getattr(config, "ADSURE_OPS_ENABLED", False) is not True:
        return None
    username = str(getattr(config, "ADSURE_OPS_USERNAME", "") or "")
    password = str(getattr(config, "ADSURE_OPS_PASSWORD", "") or "")
    if not username or not password:
        return None
    return username, password


def _authorized(settings: tuple[str, str]) -> bool:
    authorization = getattr(_request(), "authorization", None)
    if authorization is None:
        return False
    supplied_user = str(getattr(authorization, "username", "") or "")
    supplied_password = str(getattr(authorization, "password", "") or "")
    user_matches = secrets.compare_digest(supplied_user, settings[0])
    password_matches = secrets.compare_digest(supplied_password, settings[1])
    return user_matches and password_matches


def _unauthorized():
    return "", 401, {"WWW-Authenticate": 'Basic realm="Adsure maintenance"'}


def _request():
    from flask import request

    return request


def _jsonify(payload: dict):
    from flask import jsonify

    return jsonify(payload)


def _render_template(name: str):
    from flask import render_template

    return render_template(name)
