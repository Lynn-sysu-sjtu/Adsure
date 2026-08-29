"""Table scanner and the sole persistent Adsure queue processor."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time

from fields_v4 import F_物料内容, F_物料附件, F_流转_当前状态
from feishu_api import list_all_records
from job_runtime import QueueProcessor, enqueue_initial_submission
from logging_utils import configure_logging, context_fields


logger = logging.getLogger(__name__)
POLL_INTERVAL = 5
QUEUE_IDLE_SLEEP = 0.5
_LEGACY_DEDUP_FILE = "/tmp/adsure_processed_ids.json"
_LOCK_FILE = "/tmp/adsure_worker.lock"


def _text_of(raw):
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in raw
        )
    if isinstance(raw, dict):
        return raw.get("text") or raw.get("name") or ""
    return str(raw)


def is_new_submission(fields):
    """Preserve the original submission trigger without making it delivery truth."""
    status = fields.get(F_流转_当前状态, "")
    content = _text_of(fields.get(F_物料内容))
    has_attachment = bool(fields.get(F_物料附件))
    if status or not (content.strip() or has_attachment):
        return False
    created_ms = fields.get("创建时间")
    if created_ms:
        try:
            age_days = (time.time() * 1000 - int(created_ms)) / (1000 * 86400)
            if age_days > 7:
                return False
        except (TypeError, ValueError):
            logger.warning("event=invalid_submission_timestamp")
    return True


def process_record(record_id, _fields=None):
    queued = enqueue_initial_submission(record_id)
    logger.info(
        "event=initial_submission_%s %s",
        "enqueued" if queued.created else "deduplicated",
        context_fields(record_id=record_id, job_id=queued.item_id, status=queued.status),
    )
    return queued


def poll_once():
    try:
        records = list_all_records()
        for record in records:
            fields = record.get("fields", {})
            if is_new_submission(fields):
                process_record(record["record_id"], fields)
    except Exception:
        logger.exception("event=submission_scan_failed error_category=transient_network")


def _log_legacy_dedup_hint():
    if not os.path.exists(_LEGACY_DEDUP_FILE):
        return
    try:
        with open(_LEGACY_DEDUP_FILE, encoding="utf-8") as handle:
            values = json.load(handle)
        count = len(values) if isinstance(values, list) else 0
        logger.info("event=legacy_dedup_file_ignored record_count=%s", count)
    except Exception:
        logger.warning("event=legacy_dedup_file_unreadable")


def main():
    configure_logging()
    lock_fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.error("event=worker_already_running")
        lock_fd.close()
        return

    _log_legacy_dedup_hint()
    processor = QueueProcessor()
    logger.info("event=worker_started poll_interval=%s", POLL_INTERVAL)
    next_scan = 0.0
    try:
        while True:
            now = time.monotonic()
            if now >= next_scan:
                poll_once()
                next_scan = now + POLL_INTERVAL
            processed = processor.run_available(max_items=20)
            if not processed:
                time.sleep(QUEUE_IDLE_SLEEP)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
