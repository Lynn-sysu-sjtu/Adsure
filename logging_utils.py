"""Logging helpers that keep identifiers and sensitive payloads out of logs."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any


def configure_logging():
    level_name = os.environ.get("ADSURE_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def mask_identifier(value: Any) -> str:
    if value in (None, ""):
        return "-"
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:10]
    return f"id#{digest}"


def context_fields(**fields: Any) -> str:
    safe = []
    for key, value in fields.items():
        if value in (None, ""):
            continue
        if key in {"open_id", "operator_id", "recipient_id"}:
            value = mask_identifier(value)
        safe.append(f"{key}={value}")
    return " ".join(safe)
