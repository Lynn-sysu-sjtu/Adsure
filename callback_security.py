"""Optional Feishu HTTP callback verification with a compatibility-off default."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Mapping


logger = logging.getLogger(__name__)
_warned_disabled = False


def verify_http_callback(headers: Mapping[str, str], raw_body: bytes, body: dict) -> bool:
    """Return whether the callback is accepted under the current configured policy."""
    global _warned_disabled
    enabled, verification_token, encrypt_key, max_age = _settings()
    if not enabled:
        if not _warned_disabled:
            logger.warning("event=callback_verification_disabled action=configure_security_before_enabling")
            _warned_disabled = True
        return True

    if verification_token:
        received_token = body.get("token")
        if received_token and not hmac.compare_digest(str(received_token), verification_token):
            logger.error("event=callback_verification_failed category=verification_token")
            return False

    timestamp = headers.get("X-Lark-Request-Timestamp") or headers.get("x-lark-request-timestamp")
    nonce = headers.get("X-Lark-Request-Nonce") or headers.get("x-lark-request-nonce")
    signature = headers.get("X-Lark-Signature") or headers.get("x-lark-signature")

    if not encrypt_key:
        logger.error("event=callback_verification_failed category=missing_encrypt_key")
        return False
    if not timestamp or not nonce or not signature:
        logger.error("event=callback_verification_failed category=missing_signature_headers")
        return False
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        logger.error("event=callback_verification_failed category=invalid_timestamp")
        return False
    if abs(time.time() - timestamp_value) > max_age:
        logger.warning("event=callback_verification_failed category=replay_window")
        return False

    source = str(timestamp).encode() + str(nonce).encode() + encrypt_key.encode() + raw_body
    expected = hashlib.sha256(source).hexdigest()
    if not hmac.compare_digest(expected, str(signature)):
        logger.error("event=callback_verification_failed category=signature")
        return False
    return True


def _settings() -> tuple[bool, str, str, int]:
    try:
        import config
        return (
            bool(getattr(config, "FEISHU_CALLBACK_VERIFY_ENABLED", False)),
            str(getattr(config, "FEISHU_VERIFICATION_TOKEN", "") or ""),
            str(getattr(config, "FEISHU_ENCRYPT_KEY", "") or ""),
            int(getattr(config, "FEISHU_CALLBACK_MAX_AGE_SECONDS", 300)),
        )
    except ImportError:
        return False, "", "", 300
