"""SQLite-backed jobs and deliveries with idempotency and crash recovery."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import random
import sqlite3
import threading
import time
from typing import Any, Optional


PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
RETRYABLE_FAILED = "retryable_failed"
TERMINAL_FAILED = "terminal_failed"
ACTIVE_STATUSES = (PENDING, RUNNING, RETRYABLE_FAILED)


@dataclass(frozen=True)
class EnqueueResult:
    item_id: int
    created: bool
    status: str
    reason: str = "idempotency"


class SQLiteQueue:
    """Small persistent queue. Every operation uses its own DB connection."""

    def __init__(
        self,
        path: str,
        *,
        busy_timeout_ms: int = 5000,
        lease_seconds: int = 120,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 60.0,
    ):
        self.path = str(path)
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.lease_seconds = int(lease_seconds)
        self.retry_base_seconds = float(retry_base_seconds)
        self.retry_max_seconds = float(retry_max_seconds)
        self._schema_lock = threading.Lock()
        self._ensure_parent()
        self._ensure_schema()

    def _ensure_parent(self):
        if self.path == ":memory:":
            return
        Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=max(1.0, self.busy_timeout_ms / 1000),
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self):
        with self._schema_lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    status TEXT NOT NULL CHECK(status IN (
                        'pending','running','succeeded','retryable_failed','terminal_failed'
                    )),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    next_attempt_at REAL NOT NULL,
                    lease_until REAL,
                    worker_id TEXT,
                    error_category TEXT,
                    user_notice_sent INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_ai_review
                ON jobs(record_id)
                WHERE job_type = 'ai_review'
                  AND status IN ('pending','running','retryable_failed');

                CREATE INDEX IF NOT EXISTS idx_jobs_claim
                ON jobs(status, next_attempt_at, created_at);

                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    business_action TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    card_type TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    message_id TEXT,
                    status TEXT NOT NULL CHECK(status IN (
                        'pending','running','succeeded','retryable_failed','terminal_failed'
                    )),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    next_attempt_at REAL NOT NULL,
                    lease_until REAL,
                    worker_id TEXT,
                    error_category TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                );

                CREATE INDEX IF NOT EXISTS idx_deliveries_claim
                ON deliveries(status, next_attempt_at, created_at);

                CREATE TABLE IF NOT EXISTS record_rounds (
                    record_id TEXT PRIMARY KEY,
                    review_round INTEGER NOT NULL DEFAULT 1,
                    last_resubmit_key TEXT,
                    updated_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def _json(value: Optional[dict]) -> str:
        return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _row(row: Optional[sqlite3.Row]) -> Optional[dict]:
        if row is None:
            return None
        value = dict(row)
        for key in ("payload_json", "result_json"):
            raw = value.pop(key, None)
            target = key.removesuffix("_json")
            if raw:
                try:
                    value[target] = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    value[target] = {}
            else:
                value[target] = None if key == "result_json" else {}
        return value

    def enqueue_job(
        self,
        job_type: str,
        record_id: str,
        idempotency_key: str,
        payload: Optional[dict] = None,
        *,
        max_attempts: int = 5,
        run_at: Optional[float] = None,
    ) -> EnqueueResult:
        now = time.time()
        due = now if run_at is None else float(run_at)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    """
                    INSERT INTO jobs (
                        job_type, record_id, idempotency_key, payload_json, status,
                        max_attempts, next_attempt_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_type, record_id, idempotency_key, self._json(payload), PENDING,
                        int(max_attempts), due, now, now,
                    ),
                )
                item_id = int(cur.lastrowid)
                conn.commit()
                return EnqueueResult(item_id, True, PENDING, "created")
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id, status FROM jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                reason = "idempotency"
                if row is None and job_type == "ai_review":
                    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
                    row = conn.execute(
                        f"""SELECT id, status FROM jobs
                            WHERE job_type = 'ai_review' AND record_id = ?
                              AND status IN ({placeholders})
                            ORDER BY id DESC LIMIT 1""",
                        (record_id, *ACTIVE_STATUSES),
                    ).fetchone()
                    reason = "active_review"
                conn.commit()
                if row is None:
                    raise
                return EnqueueResult(int(row["id"]), False, str(row["status"]), reason)

    def enqueue_delivery(
        self,
        *,
        job_id: Optional[int],
        business_action: str,
        record_id: str,
        recipient_id: str,
        card_type: str,
        idempotency_key: str,
        payload: Optional[dict] = None,
        max_attempts: int = 5,
        run_at: Optional[float] = None,
    ) -> EnqueueResult:
        now = time.time()
        due = now if run_at is None else float(run_at)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO deliveries (
                    job_id, business_action, record_id, recipient_id, card_type,
                    idempotency_key, payload_json, status, max_attempts,
                    next_attempt_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, business_action, record_id, recipient_id, card_type,
                    idempotency_key, self._json(payload), PENDING, int(max_attempts),
                    due, now, now,
                ),
            )
            row = conn.execute(
                "SELECT id, status, created_at FROM deliveries WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("delivery insert did not return a row")
        created = cursor.rowcount == 1
        return EnqueueResult(int(row["id"]), created, str(row["status"]), "created" if created else "idempotency")

    def _claim(self, table: str, worker_id: str, now: Optional[float]) -> Optional[dict]:
        if table not in ("jobs", "deliveries"):
            raise ValueError("unsupported queue table")
        current = time.time() if now is None else float(now)
        lease_until = current + self.lease_seconds
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"""UPDATE {table}
                    SET status = ?, next_attempt_at = ?, lease_until = NULL,
                        worker_id = NULL, error_category = 'worker_interrupted', updated_at = ?
                    WHERE status = ? AND lease_until IS NOT NULL AND lease_until < ?""",
                (RETRYABLE_FAILED, current, current, RUNNING, current),
            )
            row = conn.execute(
                f"""SELECT * FROM {table}
                    WHERE status IN (?, ?) AND next_attempt_at <= ?
                    ORDER BY next_attempt_at, created_at, id LIMIT 1""",
                (PENDING, RETRYABLE_FAILED, current),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            item_id = int(row["id"])
            conn.execute(
                f"""UPDATE {table}
                    SET status = ?, attempts = attempts + 1, lease_until = ?,
                        worker_id = ?, updated_at = ? WHERE id = ?""",
                (RUNNING, lease_until, worker_id, current, item_id),
            )
            claimed = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (item_id,)).fetchone()
            conn.commit()
        return self._row(claimed)

    def claim_job(self, worker_id: str, now: Optional[float] = None) -> Optional[dict]:
        return self._claim("jobs", worker_id, now)

    def claim_delivery(self, worker_id: str, now: Optional[float] = None) -> Optional[dict]:
        return self._claim("deliveries", worker_id, now)

    def complete_job(self, job_id: int, result: Optional[dict] = None):
        self._complete("jobs", job_id, result=result)

    def complete_delivery(self, delivery_id: int, message_id: Optional[str] = None):
        self._complete("deliveries", delivery_id, message_id=message_id)

    def _complete(
        self,
        table: str,
        item_id: int,
        *,
        result: Optional[dict] = None,
        message_id: Optional[str] = None,
    ):
        now = time.time()
        fields = ["status = ?", "lease_until = NULL", "worker_id = NULL", "error_category = NULL", "updated_at = ?"]
        params: list[Any] = [SUCCEEDED, now]
        if table == "jobs":
            fields.append("result_json = ?")
            params.append(self._json(result))
        elif table == "deliveries":
            fields.append("message_id = COALESCE(?, message_id)")
            params.append(message_id)
        else:
            raise ValueError("unsupported queue table")
        params.append(int(item_id))
        with self._connect() as conn:
            conn.execute(
                f"UPDATE {table} SET {', '.join(fields)} WHERE id = ? AND status = ?",
                (*params, RUNNING),
            )

    def _backoff(self, attempts: int) -> float:
        ceiling = min(self.retry_max_seconds, self.retry_base_seconds * (2 ** max(0, attempts - 1)))
        return ceiling * random.uniform(0.8, 1.2)

    def _fail(self, table: str, item_id: int, *, retryable: bool, category: str) -> str:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT attempts, max_attempts FROM {table} WHERE id = ?",
                (int(item_id),),
            ).fetchone()
            if row is None:
                raise KeyError(item_id)
            attempts = int(row["attempts"])
            terminal = (not retryable) or attempts >= int(row["max_attempts"])
            status = TERMINAL_FAILED if terminal else RETRYABLE_FAILED
            next_at = now if terminal else now + self._backoff(attempts)
            conn.execute(
                f"""UPDATE {table}
                    SET status = ?, next_attempt_at = ?, lease_until = NULL,
                        worker_id = NULL, error_category = ?, updated_at = ?
                    WHERE id = ?""",
                (status, next_at, category, now, int(item_id)),
            )
        return status

    def fail_job(self, job_id: int, *, retryable: bool, category: str) -> str:
        return self._fail("jobs", job_id, retryable=retryable, category=category)

    def fail_delivery(self, delivery_id: int, *, retryable: bool, category: str) -> str:
        return self._fail("deliveries", delivery_id, retryable=retryable, category=category)

    def get_job(self, job_id: int) -> Optional[dict]:
        with self._connect() as conn:
            return self._row(conn.execute("SELECT * FROM jobs WHERE id = ?", (int(job_id),)).fetchone())

    def get_job_by_key(self, idempotency_key: str) -> Optional[dict]:
        with self._connect() as conn:
            return self._row(conn.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone())

    def get_latest_job(self, record_id: str, job_type: str) -> Optional[dict]:
        with self._connect() as conn:
            return self._row(conn.execute(
                """SELECT * FROM jobs WHERE record_id = ? AND job_type = ?
                    ORDER BY id DESC LIMIT 1""",
                (record_id, job_type),
            ).fetchone())

    def get_delivery_by_key(self, idempotency_key: str) -> Optional[dict]:
        with self._connect() as conn:
            return self._row(conn.execute(
                "SELECT * FROM deliveries WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone())

    def list_jobs(self) -> list[dict]:
        with self._connect() as conn:
            return [self._row(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id")]

    def list_deliveries(self) -> list[dict]:
        with self._connect() as conn:
            return [self._row(row) for row in conn.execute("SELECT * FROM deliveries ORDER BY id")]

    def current_round(self, record_id: str) -> int:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO record_rounds
                    (record_id, review_round, updated_at) VALUES (?, 1, ?)""",
                (record_id, now),
            )
            row = conn.execute(
                "SELECT review_round FROM record_rounds WHERE record_id = ?", (record_id,)
            ).fetchone()
        return int(row["review_round"])

    def advance_round_once(self, record_id: str, resubmit_key: str) -> int:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT OR IGNORE INTO record_rounds
                    (record_id, review_round, updated_at) VALUES (?, 1, ?)""",
                (record_id, now),
            )
            row = conn.execute(
                "SELECT review_round, last_resubmit_key FROM record_rounds WHERE record_id = ?",
                (record_id,),
            ).fetchone()
            if row["last_resubmit_key"] != resubmit_key:
                conn.execute(
                    """UPDATE record_rounds
                        SET review_round = review_round + 1, last_resubmit_key = ?, updated_at = ?
                        WHERE record_id = ?""",
                    (resubmit_key, now, record_id),
                )
            updated = conn.execute(
                "SELECT review_round FROM record_rounds WHERE record_id = ?", (record_id,)
            ).fetchone()
            conn.commit()
        return int(updated["review_round"])


_default_store: Optional[SQLiteQueue] = None
_default_lock = threading.Lock()


def default_db_path() -> str:
    fallback = str(Path(__file__).resolve().parent / "data" / "adsure_jobs.sqlite3")
    env_path = os.environ.get("ADSURE_DB_PATH")
    if env_path:
        return env_path
    try:
        import config
        configured = getattr(config, "ADSURE_DB_PATH", "")
        if configured:
            configured_path = Path(str(configured)).expanduser()
            if not configured_path.is_absolute():
                configured_path = Path(__file__).resolve().parent / configured_path
            return str(configured_path)
    except ImportError:
        return fallback
    return fallback


def get_store() -> SQLiteQueue:
    global _default_store
    with _default_lock:
        if _default_store is None:
            try:
                import config
                busy = int(getattr(config, "ADSURE_DB_BUSY_TIMEOUT_MS", 5000))
                lease = int(getattr(config, "ADSURE_JOB_LEASE_SECONDS", 120))
                base = float(getattr(config, "ADSURE_RETRY_BASE_SECONDS", 2))
                maximum = float(getattr(config, "ADSURE_RETRY_MAX_SECONDS", 60))
            except ImportError:
                busy, lease, base, maximum = 5000, 120, 2.0, 60.0
            _default_store = SQLiteQueue(
                default_db_path(), busy_timeout_ms=busy, lease_seconds=lease,
                retry_base_seconds=base, retry_max_seconds=maximum,
            )
        return _default_store


def reset_default_store_for_tests():
    global _default_store
    with _default_lock:
        _default_store = None
