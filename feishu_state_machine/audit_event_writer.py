"""Small non-blocking writer shared by public and internal audit producers."""

from __future__ import annotations

import logging
from typing import Optional

from logging_utils import context_fields
from reliable_queue import SQLiteQueue, get_store


logger = logging.getLogger(__name__)

INTERNAL_EVENT_TYPES = {
    "legal_cards_sync_scheduled",
    "delivery_replayed",
}

_SUMMARY_KEYS = {
    "round",
    "mode",
    "risk_level",
    "routed_to_legal",
    "source",
    "reviewer_name",
    "verdict",
    "is_edit",
    "count",
}


def append_event(
    event_type: str,
    *,
    record_id: str,
    event_key: str,
    summary: Optional[dict] = None,
    actor_role: str = "system",
    actor_name: str = "",
    job_id: Optional[int] = None,
    delivery_id: Optional[int] = None,
    store: Optional[SQLiteQueue] = None,
) -> bool:
    """Append one allowlisted payload; persistence failure is non-blocking."""
    try:
        return (store or get_store()).append_audit_event(
            record_id=record_id,
            event_type=event_type,
            event_key=event_key,
            actor_role=(
                actor_role
                if actor_role in {"system", "operator", "legal"}
                else "system"
            ),
            actor_name=str(actor_name or "")[:80],
            summary=_sanitize_summary(summary or {}),
            job_id=job_id,
            delivery_id=delivery_id,
        )
    except Exception:
        logger.exception(
            "event=audit_event_write_failed %s",
            context_fields(record_id=record_id, event_type=event_type),
        )
        return False


def record_internal_event(event_type: str, **kwargs) -> bool:
    """Record only the two maintenance events, independent of the timeline UI."""
    if event_type not in INTERNAL_EVENT_TYPES:
        return False
    return append_event(event_type, **kwargs)


def _sanitize_summary(summary: dict) -> dict:
    clean = {}
    for key in _SUMMARY_KEYS:
        value = summary.get(key)
        if isinstance(value, bool):
            clean[key] = value
        elif isinstance(value, int):
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:120]
    return clean
