"""Optional persistent synchronization of legal review cards after a verdict."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from audit_event_writer import record_internal_event
from card_templates import markdown_escape
from feature_flags import legal_card_sync_enabled
from fields_v4 import (
    F_法务_批注,
    F_法务_复核人,
    F_法务_物料裁决,
    F_流转_当前状态,
)
from logging_utils import context_fields, mask_identifier
from reliable_queue import SQLiteQueue


logger = logging.getLogger(__name__)
_ROUND_PATTERN = re.compile(r":round:(\d+)(?::|$)")
_TERMINAL_REVIEW_STATUSES = {"已通过", "需修改"}


def schedule_legal_card_updates(
    store: SQLiteQueue, job: dict, round_number: int, review_payload: dict
) -> int:
    """Create one stable optional update delivery per sent card; never raise."""
    if not legal_card_sync_enabled():
        return 0
    try:
        candidates = [
            row
            for row in store.list_succeeded_legal_deliveries(job["record_id"])
            if delivery_round(row) == int(round_number)
        ]
    except Exception:
        logger.exception(
            "event=legal_card_sync_failed stage=list %s",
            context_fields(record_id=job["record_id"], job_id=job["id"]),
        )
        return 0

    snapshot = {
        "round": int(round_number),
        "reviewer_name": str(review_payload.get("reviewer_name") or "")[:80],
        "verdict": str(review_payload.get("verdict") or "")[:20],
    }
    scheduled = 0
    for original in candidates:
        target_message_id = str(original.get("message_id") or "")
        if not target_message_id:
            continue
        message_hash = hashlib.sha256(target_message_id.encode("utf-8")).hexdigest()[:16]
        key = (
            f"legal-card-sync:review-job:{job['id']}:"
            f"message:{message_hash}"
        )
        try:
            store.enqueue_delivery(
                job_id=job["id"],
                business_action="legal_card_completed_update",
                record_id=job["record_id"],
                recipient_id=original["recipient_id"],
                card_type="legal_card_update",
                idempotency_key=key,
                payload={"target_message_id": target_message_id, **snapshot},
                max_attempts=_delivery_max_attempts(),
            )
            scheduled += 1
        except Exception:
            logger.exception(
                "event=legal_card_sync_failed stage=enqueue %s",
                context_fields(
                    record_id=job["record_id"],
                    job_id=job["id"],
                    target=mask_identifier(target_message_id),
                ),
            )

    if scheduled:
        record_internal_event(
            "legal_cards_sync_scheduled",
            record_id=job["record_id"],
            event_key=(
                f"legal-cards-sync-scheduled:job:{job['id']}:"
                f"round:{round_number}"
            ),
            summary={"round": int(round_number), "count": scheduled},
            job_id=job["id"],
            store=store,
        )
        logger.info(
            "event=legal_card_sync_scheduled %s",
            context_fields(
                record_id=job["record_id"], job_id=job["id"], count=scheduled
            ),
        )
    return scheduled


def delivery_round(delivery: dict) -> Optional[int]:
    raw = (delivery.get("payload") or {}).get("round")
    try:
        if raw not in (None, ""):
            return int(raw)
    except (TypeError, ValueError):
        pass
    match = _ROUND_PATTERN.search(str(delivery.get("idempotency_key") or ""))
    return int(match.group(1)) if match else None


def completed_card_for_delayed_delivery(
    delivery: dict, fields: dict, store: SQLiteQueue
) -> Optional[dict]:
    """Return a completed card when a current-round legal card is delivered late."""
    if not legal_card_sync_enabled():
        return None
    if fields.get(F_流转_当前状态) not in _TERMINAL_REVIEW_STATUSES:
        return None
    try:
        if delivery_round(delivery) != store.current_round(delivery["record_id"]):
            return None
    except Exception:
        logger.exception(
            "event=legal_card_sync_failed stage=delayed_check %s",
            context_fields(
                record_id=delivery.get("record_id"),
                delivery_id=delivery.get("id"),
            ),
        )
        return None
    return build_completed_legal_card(
        delivery["record_id"], completed_snapshot_from_fields(fields)
    )


def completed_snapshot_from_fields(fields: dict) -> dict:
    note = str(fields.get(F_法务_批注) or "")
    match = re.match(r"【法务：(.+?)】", note)
    reviewer = match.group(1) if match else _user_name(fields.get(F_法务_复核人))
    return {
        "reviewer_name": reviewer,
        "verdict": str(fields.get(F_法务_物料裁决) or ""),
    }


def build_completed_legal_card(record_id: str, snapshot: dict) -> dict:
    reviewer = markdown_escape(snapshot.get("reviewer_name") or "法务同事")
    verdict = markdown_escape(snapshot.get("verdict") or "已完成")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "✅ 该物料已完成法务复核",
            },
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"已由 **{reviewer}** 完成\n\n**最新裁决**\n{verdict}",
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "查看审核结果"},
                        "type": "primary",
                        "url": _workbench_url(),
                    }
                ],
            },
        ],
    }


def _user_name(raw) -> str:
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("en_name") or "")
    return str(raw or "")


def _workbench_url() -> str:
    try:
        import config

        return str(getattr(config, "WORKBENCH_URL", "http://localhost:5001"))
    except ImportError:
        return "http://localhost:5001"


def _delivery_max_attempts() -> int:
    try:
        import config

        return int(getattr(config, "ADSURE_DELIVERY_MAX_ATTEMPTS", 5))
    except ImportError:
        return 5
