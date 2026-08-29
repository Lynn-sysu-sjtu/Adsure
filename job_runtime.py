"""Business job handlers and the single reliable queue processor."""

from __future__ import annotations

import logging
import hashlib
import socket
import time
import uuid
from typing import Optional

import feishu_api
from card_templates import build_card, submitter_open_id
from error_handling import OperationError, classify_exception
from fields_v4 import (
    F_物料内容,
    F_物料附件,
    F_提交人,
    F_行业领域,
    F_预审_风险等级,
    F_预审_命中要点,
    F_审核_推荐风险等级,
    F_审核_推荐违规类型,
    F_美妆_投放平台,
    F_游戏_投放平台,
    F_保健食品_投放平台,
    F_流转_当前状态,
)
from logging_utils import context_fields
from reliable_queue import SQLiteQueue, TERMINAL_FAILED, get_store
from review_service import (
    build_update_fields,
    public_result,
    record_matches_review,
    validate_review_payload,
)


logger = logging.getLogger(__name__)


class QueueProcessor:
    def __init__(
        self, store: Optional[SQLiteQueue] = None, worker_id: Optional[str] = None
    ):
        self.store = store or get_store()
        self.worker_id = worker_id or f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self._prefer_delivery = False

    def run_once(self) -> bool:
        order = ("delivery", "job") if self._prefer_delivery else ("job", "delivery")
        for item_type in order:
            if item_type == "job":
                item = self.store.claim_job(self.worker_id)
                if item:
                    self._prefer_delivery = True
                    self._run_job(item)
                    return True
            else:
                item = self.store.claim_delivery(self.worker_id)
                if item:
                    self._prefer_delivery = False
                    self._run_delivery(item)
                    return True
        return False

    def run_available(self, max_items: int = 20) -> int:
        count = 0
        while count < max_items and self.run_once():
            count += 1
        return count

    def _run_job(self, job: dict):
        fields = context_fields(
            job_id=job["id"],
            job_type=job["job_type"],
            record_id=job["record_id"],
            idempotency_key=job["idempotency_key"],
            attempt=job["attempts"],
        )
        try:
            result = self._handle_job(job)
            self.store.complete_job(job["id"], result or {})
            logger.info("event=job_succeeded %s", fields)
        except Exception as exc:
            category, retryable = classify_exception(exc)
            status = self.store.fail_job(
                job["id"], retryable=retryable, category=category
            )
            logger.exception(
                "event=job_failed %s",
                context_fields(
                    **{
                        "job_id": job["id"],
                        "job_type": job["job_type"],
                        "record_id": job["record_id"],
                        "idempotency_key": job["idempotency_key"],
                        "attempt": job["attempts"],
                        "error_category": category,
                        "status": status,
                        "feishu_code": getattr(exc, "code", None),
                    }
                ),
            )
            if status == TERMINAL_FAILED and job["job_type"] == "ai_review":
                self.store.enqueue_job(
                    "review_failure_recovery",
                    job["record_id"],
                    f"review-failure:{job['id']}",
                    {
                        "operator_id": job.get("payload", {}).get("operator_id"),
                        "failed_job_id": job["id"],
                    },
                    max_attempts=_max_job_attempts(),
                )

    def _handle_job(self, job: dict) -> dict:
        handlers = {
            "initial_submission": self._initial_submission,
            "context_confirm": self._context_confirm,
            "ai_review": self._ai_review,
            "resubmit": self._resubmit,
            "route_to_legal": self._route_to_legal,
            "legal_review": self._legal_review,
            "review_failure_recovery": self._review_failure_recovery,
        }
        handler = handlers.get(job["job_type"])
        if handler is None:
            raise OperationError("data_validation", retryable=False)
        return handler(job)

    def _initial_submission(self, job: dict) -> dict:
        record_id = job["record_id"]
        record = feishu_api.get_record(record_id)
        fields = record.get("fields", {})
        recipient = submitter_open_id(fields)
        if not recipient:
            raise OperationError("invalid_recipient", retryable=False)
        feishu_api.update_record(record_id, {F_流转_当前状态: "运营起草"})
        round_number = self.store.current_round(record_id)
        self._enqueue_delivery(
            job,
            recipient,
            "initial_review",
            f"initial:{record_id}:round:{round_number}",
            business_action="initial_review_card",
            payload={"round": round_number},
        )
        return {"round": round_number}

    def _context_confirm(self, job: dict) -> dict:
        record_id = job["record_id"]
        payload = job["payload"]
        fields = feishu_api.get_record(record_id).get("fields", {})
        current_status = fields.get(F_流转_当前状态, "")
        if _stale_first_attempt(job, current_status, {"运营起草"}):
            return {"ignored": "stale_action"}
        recipient = payload.get("operator_id") or submitter_open_id(fields)
        if not recipient:
            raise OperationError("invalid_recipient", retryable=False)
        round_number = self.store.current_round(record_id)
        self._enqueue_delivery(
            job,
            recipient,
            "context_confirm",
            f"context-confirm:{record_id}:round:{round_number}",
            business_action="context_confirm_card",
            payload={"round": round_number},
        )
        return {"round": round_number}

    def _ai_review(self, job: dict) -> dict:
        record_id = job["record_id"]
        payload = job["payload"]
        before = feishu_api.get_record(record_id).get("fields", {})
        completed_routings = {"待运营修改", "待法务复核", "运营补资料"}
        current_status = before.get(F_流转_当前状态, "")
        if _stale_first_attempt(job, current_status, {"运营起草"}):
            return {"ignored": "stale_action"}
        if job["attempts"] > 1 and current_status in completed_routings:
            routing = current_status
            logger.info(
                "event=review_retry_confirmed_existing_result %s",
                context_fields(job_id=job["id"], record_id=record_id, routing=routing),
            )
        else:
            feishu_api.update_record(record_id, {F_流转_当前状态: "AI预审中"})
            from predictor import execute

            routing, _result = execute(record_id, payload.get("mode") or "标准")
        fields = feishu_api.get_record(record_id).get("fields", {})
        recipient = payload.get("operator_id") or submitter_open_id(fields)
        round_number = int(payload.get("round") or self.store.current_round(record_id))

        if routing == "待运营修改":
            if recipient:
                self._enqueue_delivery(
                    job,
                    recipient,
                    "operator_result",
                    f"operator-result:{record_id}:round:{round_number}",
                    business_action="review_result",
                    payload={"round": round_number},
                )
        elif routing == "运营补资料":
            if recipient:
                self._enqueue_delivery(
                    job,
                    recipient,
                    "operator_more_info",
                    f"operator-more-info:{record_id}:round:{round_number}",
                    business_action="request_more_info",
                    payload={"round": round_number},
                )
        elif routing == "待法务复核":
            self._create_legal_deliveries(job, round_number)
            if recipient:
                self._enqueue_delivery(
                    job,
                    recipient,
                    "operator_transferred",
                    f"operator-transferred:{record_id}:round:{round_number}",
                    business_action="legal_handoff_accepted",
                    payload={"round": round_number},
                )
        else:
            raise OperationError("data_validation", retryable=False)
        return {"routing": routing, "round": round_number}

    def _resubmit(self, job: dict) -> dict:
        record_id = job["record_id"]
        payload = job["payload"]
        first_record = None
        if job["attempts"] == 1:
            first_record = feishu_api.get_record(record_id)
            current_status = first_record.get("fields", {}).get(F_流转_当前状态, "")
            if _stale_first_attempt(
                job,
                current_status,
                {"待运营修改", "运营补资料", "需修改"},
            ):
                return {"ignored": "stale_action"}
        round_number = self.store.advance_round_once(record_id, job["idempotency_key"])
        feishu_api.update_record(record_id, {F_流转_当前状态: "运营起草"})
        fields = (
            first_record.get("fields", {})
            if first_record is not None
            else feishu_api.get_record(record_id).get("fields", {})
        )
        recipient = payload.get("operator_id") or submitter_open_id(fields)
        if not recipient:
            raise OperationError("invalid_recipient", retryable=False)
        self._enqueue_delivery(
            job,
            recipient,
            "initial_review",
            f"initial:{record_id}:round:{round_number}",
            business_action="resubmit_review_card",
            payload={"round": round_number},
        )
        return {"round": round_number}

    def _route_to_legal(self, job: dict) -> dict:
        record_id = job["record_id"]
        payload = job["payload"]
        first_record = None
        if job["attempts"] == 1:
            first_record = feishu_api.get_record(record_id)
            current_status = first_record.get("fields", {}).get(F_流转_当前状态, "")
            allowed = (
                {"运营起草"}
                if payload.get("source") == "skip_review"
                else {"待运营修改"}
            )
            if _stale_first_attempt(job, current_status, allowed):
                return {"ignored": "stale_action"}
        round_number = int(payload.get("round") or self.store.current_round(record_id))
        feishu_api.update_record(record_id, {F_流转_当前状态: "待法务复核"})
        count = self._create_legal_deliveries(job, round_number)
        if payload.get("source") == "escalate_to_legal":
            fields = (
                first_record.get("fields", {})
                if first_record is not None
                else feishu_api.get_record(record_id).get("fields", {})
            )
            recipient = payload.get("operator_id") or submitter_open_id(fields)
            if recipient:
                self._enqueue_delivery(
                    job,
                    recipient,
                    "operator_transferred",
                    f"operator-transferred:{record_id}:round:{round_number}",
                    business_action="legal_handoff_accepted",
                    payload={"round": round_number},
                )
        return {"legal_recipient_count": count, "round": round_number}

    def _create_legal_deliveries(self, job: dict, round_number: int) -> int:
        try:
            import config

            department = getattr(config, "LEGAL_DEPT_NAME", "法律与合规")
        except ImportError:
            department = "法律与合规"
        recipients = feishu_api.get_dept_open_ids(department)
        if not recipients:
            raise OperationError("invalid_recipient", retryable=False)
        for recipient in sorted(set(recipients)):
            recipient_key = hashlib.sha256(str(recipient).encode("utf-8")).hexdigest()[
                :16
            ]
            self._enqueue_delivery(
                job,
                recipient,
                "legal_review",
                f"legal:{job['record_id']}:round:{round_number}:recipient:{recipient_key}",
                business_action="legal_review_notification",
            )
        return len(set(recipients))

    def _legal_review(self, job: dict) -> dict:
        record_id = job["record_id"]
        payload = job["payload"]
        errors = validate_review_payload(payload)
        if errors:
            raise OperationError("data_validation", retryable=False)

        record = feishu_api.get_record(record_id)
        current_fields = record.get("fields", {})
        if not record_matches_review(current_fields, payload):
            update_fields = build_update_fields(payload, current_fields)
            feishu_api.update_record(record_id, update_fields)

        self._save_correction_noncritical(record_id, payload)
        if payload.get("notify_operator", True):
            latest = feishu_api.get_record(record_id).get("fields", {})
            recipient = submitter_open_id(latest)
            if recipient:
                self._enqueue_delivery(
                    job,
                    recipient,
                    "verdict",
                    f"verdict:{record_id}:job:{job['id']}",
                    business_action="legal_verdict_notification",
                    payload={"round": self.store.current_round(record_id)},
                )
            else:
                logger.warning(
                    "event=verdict_recipient_missing %s",
                    context_fields(job_id=job["id"], record_id=record_id),
                )
        return public_result(payload)

    def _review_failure_recovery(self, job: dict) -> dict:
        record_id = job["record_id"]
        failed_job_id = job["payload"].get("failed_job_id")
        round_number = self.store.advance_round_once(
            record_id,
            f"failure-recovery:{failed_job_id}",
        )
        feishu_api.update_record(record_id, {F_流转_当前状态: "运营起草"})
        fields = feishu_api.get_record(record_id).get("fields", {})
        recipient = job["payload"].get("operator_id") or submitter_open_id(fields)
        if recipient:
            self._enqueue_delivery(
                job,
                recipient,
                "final_failure",
                f"failure-notice:{failed_job_id}",
                business_action="review_terminal_failure",
                payload={"round": round_number},
                max_attempts=_delivery_max_attempts(),
            )
        return {"recovered": True, "round": round_number}

    def _enqueue_delivery(
        self,
        job: dict,
        recipient: str,
        card_type: str,
        key: str,
        *,
        business_action: str,
        payload: Optional[dict] = None,
        max_attempts: Optional[int] = None,
    ):
        self.store.enqueue_delivery(
            job_id=job["id"],
            business_action=business_action,
            record_id=job["record_id"],
            recipient_id=recipient,
            card_type=card_type,
            idempotency_key=key,
            payload=payload,
            max_attempts=max_attempts or _delivery_max_attempts(),
        )

    def _run_delivery(self, delivery: dict):
        log_fields = {
            "delivery_id": delivery["id"],
            "record_id": delivery["record_id"],
            "card_type": delivery["card_type"],
            "idempotency_key": delivery["idempotency_key"],
            "recipient_id": delivery["recipient_id"],
            "attempt": delivery["attempts"],
        }
        try:
            fields = {}
            if delivery["card_type"] != "final_failure":
                fields = feishu_api.get_record(delivery["record_id"]).get("fields", {})
            payload = dict(delivery.get("payload") or {})
            if delivery["card_type"] == "initial_review":
                image_key = self._optional_initial_image(fields, delivery)
                if image_key:
                    payload["image_key"] = image_key
            card = build_card(
                delivery["card_type"], delivery["record_id"], fields, payload
            )
            request_uuid = str(
                uuid.uuid5(uuid.NAMESPACE_URL, delivery["idempotency_key"])
            )
            result = feishu_api.send_card(
                delivery["recipient_id"],
                card,
                idempotency_uuid=request_uuid,
            )
            self.store.complete_delivery(delivery["id"], result.get("message_id"))
            logger.info(
                "event=delivery_succeeded %s",
                context_fields(
                    **log_fields,
                    message_id=result.get("message_id"),
                    request_id=result.get("request_id"),
                    feishu_code=result.get("code"),
                ),
            )
        except Exception as exc:
            category, retryable = classify_exception(exc)
            status = self.store.fail_delivery(
                delivery["id"],
                retryable=retryable,
                category=category,
            )
            logger.exception(
                "event=delivery_failed %s",
                context_fields(
                    **log_fields,
                    error_category=category,
                    status=status,
                    feishu_code=getattr(exc, "code", None),
                ),
            )

    def _optional_initial_image(self, fields: dict, delivery: dict) -> Optional[str]:
        if str(fields.get(F_物料内容) or "").strip():
            return None
        attachments = fields.get(F_物料附件) or []
        if isinstance(attachments, dict):
            attachments = [attachments]
        image = next(
            (
                item
                for item in attachments
                if isinstance(item, dict) and item.get("file_token")
            ),
            None,
        )
        if not image:
            return None
        try:
            return feishu_api.upload_image(
                feishu_api.download_attachment(image["file_token"])
            )
        except Exception:
            logger.warning(
                "event=initial_thumbnail_degraded %s",
                context_fields(
                    delivery_id=delivery["id"], record_id=delivery["record_id"]
                ),
            )
            return None

    def _save_correction_noncritical(self, record_id: str, data: dict):
        feedback = public_result(data)["feedback_type"]
        if feedback not in {"refine", "override"}:
            return
        try:
            import preference_memory

            fields = feishu_api.get_record(record_id).get("fields", {})
            content = _plain_text(fields.get(F_物料内容))[:120]
            industry = fields.get(F_行业领域, "")
            platform_field = {
                "美妆": F_美妆_投放平台,
                "游戏": F_游戏_投放平台,
                "保健食品": F_保健食品_投放平台,
            }.get(industry, "")
            raw_platform = fields.get(platform_field, "")
            platform = (
                "、".join(raw_platform)
                if isinstance(raw_platform, list)
                else str(raw_platform or "")
            )
            risk = str(fields.get(F_审核_推荐风险等级, ""))
            violation_types = fields.get(F_审核_推荐违规类型, [])
            if not isinstance(violation_types, list):
                violation_types = [str(violation_types)] if violation_types else []
            preference_memory.save_correction(
                record_id=record_id,
                content_snippet=content,
                industry=industry,
                platform=platform,
                ai_risk_level=risk,
                ai_violation_types=violation_types,
                feedback_type=feedback,
                objection_fields=data.get("objection_fields", []),
                correct_judgment=str(data.get("correct_judgment") or "").strip(),
                reason=str(
                    data.get("reject_reason") or data.get("supplement_reason") or ""
                ).strip(),
                idempotency_key=str(data.get("request_hash") or ""),
            )
        except Exception:
            logger.exception(
                "event=correction_persistence_degraded %s",
                context_fields(
                    record_id=record_id, error_category="noncritical_persistence"
                ),
            )


def enqueue_initial_submission(record_id: str, *, store: Optional[SQLiteQueue] = None):
    queue = store or get_store()
    return queue.enqueue_job(
        "initial_submission",
        record_id,
        f"initial-submission:{record_id}",
        {},
        max_attempts=_max_job_attempts(),
    )


def enqueue_legal_review(
    record_id: str,
    idempotency_key: str,
    payload: dict,
    *,
    store: Optional[SQLiteQueue] = None,
):
    queue = store or get_store()
    return queue.enqueue_job(
        "legal_review",
        record_id,
        f"legal-review:{idempotency_key}",
        payload,
        max_attempts=_max_job_attempts(),
    )


def _plain_text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(
            (
                str(item.get("text") or item.get("name") or "")
                if isinstance(item, dict)
                else str(item)
            )
            for item in raw
        )
    if isinstance(raw, dict):
        return str(raw.get("text") or raw.get("name") or "")
    return str(raw)


def _max_job_attempts() -> int:
    try:
        import config

        return int(getattr(config, "ADSURE_JOB_MAX_ATTEMPTS", 5))
    except ImportError:
        return 5


def _delivery_max_attempts() -> int:
    try:
        import config

        return int(getattr(config, "ADSURE_DELIVERY_MAX_ATTEMPTS", 5))
    except ImportError:
        return 5


def _stale_first_attempt(
    job: dict, current_status: str, allowed_statuses: set[str]
) -> bool:
    if int(job.get("attempts") or 0) != 1 or current_status in allowed_statuses:
        return False
    logger.info(
        "event=stale_action_ignored %s",
        context_fields(
            job_id=job.get("id"),
            record_id=job.get("record_id"),
            action=job.get("payload", {}).get("action")
            or job.get("payload", {}).get("source"),
            current_status=current_status,
        ),
    )
    return True
