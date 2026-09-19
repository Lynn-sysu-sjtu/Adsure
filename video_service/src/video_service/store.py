"""SQLite-backed job persistence and single-worker queue."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .schemas import JobStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  record_id TEXT NOT NULL,
  request_id TEXT NOT NULL UNIQUE,
  material_id TEXT NOT NULL UNIQUE,
  file_sha256 TEXT NOT NULL,
  source_path TEXT NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  result_json TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  leased_at TEXT,
  heartbeat_at TEXT
  ,options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
"""

MIGRATIONS = (
    "ALTER TABLE jobs ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            for statement in MIGRATIONS:
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError:
                    pass

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_job(self, *, source_path: Path, file_sha256: str, record_id: str | None,
                   material_id: str | None, dedupe_by_hash: bool,
                   options: dict[str, Any] | None = None) -> tuple[dict, bool]:
        record_id = (record_id or "").strip() or uuid.uuid4().hex
        material_id = (material_id or "").strip() or uuid.uuid4().hex
        request_id = record_id
        now = utc_now()
        with self._lock, self.connect() as conn:
            if record_id:
                row = conn.execute("SELECT * FROM jobs WHERE request_id=?", (record_id,)).fetchone()
                if row:
                    return dict(row), True
            if dedupe_by_hash:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE file_sha256=? ORDER BY created_at DESC LIMIT 1",
                    (file_sha256,)).fetchone()
                if row:
                    return dict(row), True
            job_id = uuid.uuid4().hex
            conn.execute(
                """INSERT INTO jobs(job_id,record_id,request_id,material_id,file_sha256,source_path,
                   status,attempts,created_at,updated_at,options_json)
                   VALUES(?,?,?,?,?,?, 'queued',0,?,?,?)""",
                (job_id, record_id, request_id, material_id, file_sha256, str(source_path),
                 now, now, json.dumps(options or {}, ensure_ascii=False)))
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(row), False

    def get(self, job_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def claim_next(self, stale_seconds: int) -> Optional[dict]:
        now = utc_now()
        with self._lock, self.connect() as conn:
            stale = conn.execute("SELECT job_id,heartbeat_at,attempts FROM jobs WHERE status='processing'").fetchall()
            for row in stale:
                try:
                    heartbeat = datetime.fromisoformat(row["heartbeat_at"])
                    if heartbeat.tzinfo is None:
                        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
                except Exception:
                    age = stale_seconds + 1
                if age >= stale_seconds and row["attempts"] < int(os.getenv("VIDEO_SERVICE_MAX_ATTEMPTS", "3")):
                    conn.execute("UPDATE jobs SET status='queued',leased_at=NULL,heartbeat_at=NULL,updated_at=? WHERE job_id=?",
                                 (now, row["job_id"]))
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status='processing', attempts=attempts+1, leased_at=?, "
                "heartbeat_at=?, updated_at=? WHERE job_id=?", (now, now, now, row["job_id"]))
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
            return dict(row)

    def heartbeat(self, job_id: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET heartbeat_at=?, updated_at=? WHERE job_id=?",
                         (utc_now(), utc_now(), job_id))

    def finish(self, job_id: str, status: JobStatus, result: dict, warnings: list[str], error: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, result_json=?, error=?, leased_at=NULL, heartbeat_at=NULL, updated_at=? WHERE job_id=?",
                (status, json.dumps(result, ensure_ascii=False), error, utc_now(), job_id))

    def requeue_or_fail(self, job_id: str, error: str) -> None:
        max_attempts = int(os.getenv("VIDEO_SERVICE_MAX_ATTEMPTS", "3"))
        with self.connect() as conn:
            row = conn.execute("SELECT attempts FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            next_status = "queued" if row and row["attempts"] < max_attempts else "failed"
            conn.execute(
                "UPDATE jobs SET status=?, error=?, leased_at=NULL, heartbeat_at=NULL, updated_at=? WHERE job_id=?",
                (next_status, error, utc_now(), job_id))

    def result(self, job_id: str) -> dict | None:
        row = self.get(job_id)
        return json.loads(row["result_json"]) if row.get("result_json") else None
