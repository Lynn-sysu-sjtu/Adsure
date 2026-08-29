"""Adsure legal workbench and HTTP callback transport."""

from __future__ import annotations

import datetime
import hashlib
import logging
import os
import re
import time

from flask import Flask, Response, jsonify, render_template, request

import feishu_api
import preference_memory
from callback_security import verify_http_callback
from card_action_service import handle_card_action, parse_http_action
from fields_v4 import (
    F_物料编号, F_行业领域, F_物料内容, F_物料附件, F_提交人, F_提交时间,
    F_紧急程度, F_补充背景资料,
    F_美妆_物料类型, F_美妆_投放平台, F_美妆_产品品类,
    F_美妆_产品备案名称, F_美妆_物料涉及场景, F_美妆_核心宣称功效,
    F_游戏_物料类型, F_游戏_投放平台, F_游戏_产品品类,
    F_游戏_游戏名称, F_游戏_物料涉及场景, F_游戏_IP名称,
    F_保健食品_物料类型, F_保健食品_投放平台, F_保健食品_产品品类,
    F_保健食品_物料涉及场景, F_保健食品_核心宣称功效,
    F_保健食品_产品备案名称, F_保健食品_批准文号,
    F_预审_风险等级, F_预审_命中要点, F_预审_修改建议,
    F_预审_运营修改记录, F_预审_运营是否采纳建议,
    F_审核_审核模式, F_审核_审核意见, F_审核_关键实体抽取,
    F_审核_高风险词命中, F_审核_平台规则预检, F_审核_备案核查结果,
    F_审核_推荐违规类型, F_审核_推荐风险等级,
    F_法务_AI意见评价, F_法务_物料裁决, F_法务_异议字段,
    F_法务_补充或驳回理由, F_法务_驳回正确判定, F_法务_最终修改意见,
    F_法务_批注, F_法务_复核人, F_法务_复核时间,
    F_流转_当前状态, F_流转_反馈类型, F_流转_驳回次数,
)
from job_runtime import enqueue_legal_review
from logging_utils import configure_logging, context_fields
from reliable_queue import ACTIVE_STATUSES, SUCCEEDED, TERMINAL_FAILED, get_store
from review_service import validate_review_payload
from user_messages import (
    ACTION_ACCEPTED, ACTION_RETRY, REVIEW_SUBMIT_UNAVAILABLE, STALE_CARD,
    WORKBENCH_UNAVAILABLE,
)


app = Flask(__name__)
logger = logging.getLogger(__name__)
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


@app.route("/feishu/card", methods=["POST"])
def feishu_card_callback():
    raw_body = request.get_data(cache=True)
    body = request.get_json(silent=True) or {}
    if not verify_http_callback(request.headers, raw_body, body):
        return jsonify({"toast": {"type": "error", "content": STALE_CARD}}), 401
    if body.get("type") == "url_verification":
        return jsonify({"challenge": body.get("challenge", "")})
    try:
        result = handle_card_action(parse_http_action(body))
        return jsonify({"toast": {"type": result.toast_type, "content": result.message}})
    except Exception:
        logger.exception("event=http_card_callback_failed error_category=callback_processing")
        return jsonify({"toast": {"type": "error", "content": ACTION_RETRY}})


def _name_of_user(raw):
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        return raw.get("name") or raw.get("en_name") or ""
    return raw if isinstance(raw, str) else ""


def _parse_reviewer(note: str) -> str:
    match = re.match(r"【法务：(.+?)】", note or "")
    return match.group(1) if match else ""


def _ts_to_str(raw):
    if not raw:
        return ""
    try:
        value = datetime.datetime.fromtimestamp(int(raw) / 1000)
        return value.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return ""


def _as_list(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw] if raw else []


def _as_text(raw):
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        output = []
        for item in raw:
            if isinstance(item, dict):
                text = item.get("text") or item.get("name") or ""
                if text:
                    output.append(text)
            else:
                output.append(str(item))
        return "".join(output)
    if isinstance(raw, dict):
        return raw.get("text") or raw.get("name") or ""
    return str(raw)


def _norm_risk(value):
    if not value:
        return ""
    text = str(value).strip()
    return {"高": "高风险", "中": "中风险", "低": "低风险", "无明显风险": "低风险"}.get(text, text)


def _get_platform(fields, industry=None):
    industry = industry if industry is not None else fields.get(F_行业领域, "")
    platform_field = {
        "美妆": F_美妆_投放平台,
        "游戏": F_游戏_投放平台,
        "保健食品": F_保健食品_投放平台,
    }.get(industry, "")
    raw = fields.get(platform_field, "")
    return "、".join(raw) if isinstance(raw, list) else str(raw or "")


@app.route("/")
def index():
    return render_template("workbench.html")


@app.route("/api/records")
def get_records():
    try:
        records = [
            normalize_record(item.get("record_id"), item.get("fields", {}))
            for item in feishu_api.list_all_records()
        ]
        order = {"高风险": 0, "中风险": 1, "低风险": 2, "高": 0, "中": 1, "低": 2}
        records.sort(key=lambda item: order.get(item["风险等级"], 9))
        return jsonify(records)
    except Exception:
        logger.exception("event=workbench_records_load_failed error_category=transient_network")
        return jsonify({
            "success": False, "code": "TEMPORARY_UNAVAILABLE", "message": WORKBENCH_UNAVAILABLE,
        }), 503


@app.route("/api/records/<record_id>/review", methods=["POST"])
def submit_review(record_id):
    data = request.get_json(silent=True) or {}
    errors = validate_review_payload(data)
    if errors:
        return jsonify({
            "success": False, "code": "INVALID_INPUT", "message": next(iter(errors.values())),
            "field_errors": errors,
        }), 400

    idempotency_key = request.headers.get("Idempotency-Key") or data.get("idempotency_key", "")
    if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        return jsonify({
            "success": False, "code": "INVALID_INPUT", "message": REVIEW_SUBMIT_UNAVAILABLE,
        }), 400

    allowed = {
        "ai_opinion", "verdict", "reviewer_name", "objection_fields", "supplement_reason",
        "reject_reason", "correct_judgment", "final_suggestion", "note", "notify_operator",
    }
    payload = {key: data.get(key) for key in allowed if key in data}
    payload["submitted_at_ms"] = int(time.time() * 1000)
    request_hash = hashlib.sha256(
        repr(sorted((key, repr(value)) for key, value in payload.items() if key != "submitted_at_ms")).encode("utf-8")
    ).hexdigest()
    payload["request_hash"] = request_hash

    try:
        queued = enqueue_legal_review(record_id, idempotency_key, payload)
        job = get_store().get_job(queued.item_id)
        if not queued.created and job and job.get("payload", {}).get("request_hash") != request_hash:
            return jsonify({
                "success": False, "code": "IDEMPOTENCY_CONFLICT", "message": REVIEW_SUBMIT_UNAVAILABLE,
            }), 409
        return _review_job_response(job)
    except Exception:
        logger.exception("event=legal_review_enqueue_failed %s", context_fields(record_id=record_id))
        return jsonify({
            "success": False, "code": "TEMPORARY_UNAVAILABLE", "message": REVIEW_SUBMIT_UNAVAILABLE,
        }), 503


@app.route("/api/review-operations/<operation_key>")
def get_review_operation(operation_key):
    if not _IDEMPOTENCY_PATTERN.fullmatch(operation_key or ""):
        return jsonify({
            "success": False, "operation_status": "unknown", "message": REVIEW_SUBMIT_UNAVAILABLE,
        }), 404
    job = get_store().get_job_by_key(f"legal-review:{operation_key}")
    if job is None:
        return jsonify({
            "success": False, "operation_status": "unknown", "message": REVIEW_SUBMIT_UNAVAILABLE,
        }), 404
    return _review_job_response(job)


def _review_job_response(job):
    if job and job["status"] == SUCCEEDED:
        result = dict(job.get("result") or {})
        result.update({"success": True, "operation_status": "succeeded", "message": "裁决已提交"})
        return jsonify(result), 200
    if job and job["status"] == TERMINAL_FAILED:
        return jsonify({
            "success": False, "operation_status": "failed", "message": REVIEW_SUBMIT_UNAVAILABLE,
        }), 503
    if job and job["status"] in ACTIVE_STATUSES:
        return jsonify({
            "success": True, "accepted": True, "operation_status": "pending", "message": ACTION_ACCEPTED,
        }), 202
    return jsonify({
        "success": False, "operation_status": "unknown", "message": REVIEW_SUBMIT_UNAVAILABLE,
    }), 503


def normalize_record(record_id, fields):
    return {
        "id": record_id,
        "物料编号": str(fields.get(F_物料编号, "")),
        "行业领域": fields.get(F_行业领域, ""),
        "投放平台": _get_platform(fields),
        "物料内容": _as_text(fields.get(F_物料内容)),
        "物料附件": [
            {"file_token": item.get("file_token"), "name": item.get("name", "")}
            for item in _as_list(fields.get(F_物料附件))
            if isinstance(item, dict) and item.get("file_token")
        ],
        "提交人": _name_of_user(fields.get(F_提交人)),
        "提交时间": _ts_to_str(fields.get(F_提交时间) or fields.get("创建时间")),
        "紧急程度": fields.get(F_紧急程度, ""),
        "预审_风险等级": _norm_risk(fields.get(F_预审_风险等级, "")),
        "预审_命中要点": _as_text(fields.get(F_预审_命中要点)),
        "预审_修改建议": _as_text(fields.get(F_预审_修改建议)),
        "预审_运营修改记录": _as_text(fields.get(F_预审_运营修改记录)),
        "预审_运营是否采纳建议": fields.get(F_预审_运营是否采纳建议, ""),
        "审核模式": fields.get(F_审核_审核模式, ""),
        "AI审核意见": _as_text(fields.get(F_审核_审核意见)),
        "关键实体抽取": _as_text(fields.get(F_审核_关键实体抽取)),
        "AI抽取-高风险词命中": _as_text(fields.get(F_审核_高风险词命中)),
        "平台规则预检": _as_text(fields.get(F_审核_平台规则预检)),
        "AI抽取-备案核查结果": _as_text(fields.get(F_审核_备案核查结果)),
        "违规类型": _as_list(fields.get(F_审核_推荐违规类型, [])),
        "风险等级": _norm_risk(fields.get(F_审核_推荐风险等级, "")),
        "AI意见评价": fields.get(F_法务_AI意见评价, ""),
        "物料裁决": fields.get(F_法务_物料裁决, ""),
        "异议字段": _as_list(fields.get(F_法务_异议字段, [])),
        "法务补充或驳回理由": _as_text(fields.get(F_法务_补充或驳回理由)),
        "驳回正确判定": _as_text(fields.get(F_法务_驳回正确判定)),
        "最终修改意见": _as_text(fields.get(F_法务_最终修改意见)),
        "法务批注": _as_text(fields.get(F_法务_批注)),
        "法务审核人": _parse_reviewer(_as_text(fields.get(F_法务_批注))) or _name_of_user(fields.get(F_法务_复核人)),
        "法务复核时间": _ts_to_str(fields.get(F_法务_复核时间)),
        "美妆_物料类型": fields.get(F_美妆_物料类型, ""),
        "美妆_产品品类": fields.get(F_美妆_产品品类, ""),
        "美妆_产品备案名称": _as_text(fields.get(F_美妆_产品备案名称)),
        "美妆_物料涉及场景": _as_list(fields.get(F_美妆_物料涉及场景, [])),
        "美妆_核心宣称功效": _as_text(fields.get(F_美妆_核心宣称功效)),
        "游戏_物料类型": fields.get(F_游戏_物料类型, ""),
        "游戏_产品品类": fields.get(F_游戏_产品品类, ""),
        "游戏_游戏名称": _as_text(fields.get(F_游戏_游戏名称)),
        "游戏_物料涉及场景": _as_list(fields.get(F_游戏_物料涉及场景, [])),
        "游戏_IP名称": _as_text(fields.get(F_游戏_IP名称)),
        "保健食品_物料类型": fields.get(F_保健食品_物料类型, ""),
        "保健食品_产品品类": fields.get(F_保健食品_产品品类, ""),
        "保健食品_产品备案名称": _as_text(fields.get(F_保健食品_产品备案名称)),
        "保健食品_批准文号": _as_text(fields.get(F_保健食品_批准文号)),
        "保健食品_物料涉及场景": _as_list(fields.get(F_保健食品_物料涉及场景, [])),
        "保健食品_核心宣称功效": _as_text(fields.get(F_保健食品_核心宣称功效)),
        "补充背景资料": _as_text(fields.get(F_补充背景资料)),
        "审核状态": fields.get(F_流转_当前状态, ""),
        "反馈类型": fields.get(F_流转_反馈类型, ""),
        "驳回次数": fields.get(F_流转_驳回次数, 0),
    }


@app.route("/api/attachment/<file_token>")
def proxy_attachment(file_token):
    cache_dir = "/tmp/adsure_img_cache"
    os.makedirs(cache_dir, exist_ok=True)
    safe_name = hashlib.sha256(file_token.encode("utf-8")).hexdigest() + ".thumb.jpg"
    cache_path = os.path.join(cache_dir, safe_name)
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as handle:
            thumbnail = handle.read()
    else:
        try:
            image_bytes = feishu_api.download_attachment(file_token)
        except Exception:
            logger.warning("event=attachment_load_degraded")
            return Response(status=404)
        try:
            import io
            from PIL import Image
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            image.thumbnail((900, 900), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=75, optimize=True)
            thumbnail = buffer.getvalue()
            with open(cache_path, "wb") as handle:
                handle.write(thumbnail)
        except Exception:
            logger.warning("event=attachment_thumbnail_degraded")
            thumbnail = image_bytes
    response = Response(thumbnail, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.route("/api/corrections")
def list_corrections():
    try:
        return jsonify(preference_memory.list_all())
    except Exception:
        logger.exception("event=corrections_load_failed error_category=noncritical_persistence")
        return jsonify([])


@app.route("/api/corrections/<correction_id>/status", methods=["POST"])
def update_correction_status(correction_id):
    status = (request.get_json(silent=True) or {}).get("status", "paused")
    if status not in ("active", "paused"):
        return jsonify({"success": False, "code": "INVALID_INPUT", "message": ACTION_RETRY}), 400
    return jsonify({"success": preference_memory.set_status(correction_id, status)})


@app.route("/api/corrections/<correction_id>", methods=["DELETE"])
def delete_correction(correction_id):
    return jsonify({"success": preference_memory.delete_correction(correction_id)})


@app.route("/api/records/<record_id>/cases")
def get_cases(record_id):
    try:
        from config import CASE_ENGINE_API_KEY, CASE_ENGINE_URL
        import requests as external_requests
        if not CASE_ENGINE_URL:
            return jsonify({"cases": [], "record_id": record_id})
        fields = feishu_api.get_record(record_id).get("fields", {})
        industry = _as_text(fields.get(F_行业领域, ""))
        content = _as_text(fields.get(F_物料内容, ""))
        platform_field = {
            "美妆": F_美妆_投放平台,
            "游戏": F_游戏_投放平台,
            "保健食品": F_保健食品_投放平台,
        }.get(industry, "")
        platform_raw = fields.get(platform_field, "")
        platform = platform_raw if isinstance(platform_raw, list) else ([str(platform_raw)] if platform_raw else [])
        response = external_requests.post(
            f"{CASE_ENGINE_URL}/cases/retrieve",
            headers={"X-API-Key": CASE_ENGINE_API_KEY, "Content-Type": "application/json"},
            json={"content": content, "industry": industry, "platform": platform, "top_k": 3},
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise ValueError("case engine response rejected")
        return jsonify({"cases": data.get("data", {}).get("cases", []), "record_id": record_id})
    except Exception:
        logger.warning("event=case_retrieval_degraded %s", context_fields(record_id=record_id))
        return jsonify({"cases": [], "record_id": record_id})


if __name__ == "__main__":
    configure_logging()
    try:
        import config
        debug = bool(getattr(config, "FLASK_DEBUG", False))
    except ImportError:
        debug = False
    app.run(host="0.0.0.0", debug=debug, port=5001, use_reloader=False)
