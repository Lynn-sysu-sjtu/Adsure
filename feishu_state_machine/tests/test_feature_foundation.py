import os
import sqlite3
import sys
import tempfile
import types
import unittest

import feature_flags
from reliable_queue import SQLiteQueue


class FeatureFoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "queue.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_database_upgrade_is_additive_and_repeatable(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    status TEXT NOT NULL,
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
                CREATE TABLE deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    business_action TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    card_type TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    message_id TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    next_attempt_at REAL NOT NULL,
                    lease_until REAL,
                    worker_id TEXT,
                    error_category TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE record_rounds (
                    record_id TEXT PRIMARY KEY,
                    review_round INTEGER NOT NULL DEFAULT 1,
                    last_resubmit_key TEXT,
                    updated_at REAL NOT NULL
                );
                INSERT INTO jobs (
                    job_type, record_id, idempotency_key, status, max_attempts,
                    next_attempt_at, created_at, updated_at
                ) VALUES ('noop', 'rec-old', 'job-old', 'succeeded', 2, 1, 1, 1);
                INSERT INTO deliveries (
                    business_action, record_id, recipient_id, card_type,
                    idempotency_key, status, max_attempts, next_attempt_at,
                    created_at, updated_at
                ) VALUES (
                    'old', 'rec-old', 'ou-old', 'initial_review',
                    'delivery-old', 'succeeded', 2, 1, 1, 1
                );
                INSERT INTO record_rounds (record_id, review_round, updated_at)
                VALUES ('rec-old', 4, 1);
                """
            )

        first = SQLiteQueue(self.db_path)
        second = SQLiteQueue(self.db_path)

        self.assertEqual(first.list_jobs()[0]["idempotency_key"], "job-old")
        self.assertEqual(first.list_deliveries()[0]["replay_count"], 0)
        self.assertEqual(second.current_round("rec-old"), 4)
        with sqlite3.connect(self.db_path) as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(deliveries)")]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(columns.count("replay_count"), 1)
        self.assertIn("app_settings", tables)
        self.assertIn("audit_events", tables)

    def test_setting_is_visible_between_store_instances(self):
        first = SQLiteQueue(self.db_path)
        second = SQLiteQueue(self.db_path)
        self.assertIsNone(first.get_setting("memory_center_enabled"))
        first.set_setting("memory_center_enabled", "true")
        self.assertEqual(second.get_setting("memory_center_enabled"), "true")
        second.set_setting("memory_center_enabled", "true")
        self.assertEqual(first.get_setting("memory_center_enabled"), "true")

    def test_audit_event_key_is_unique(self):
        store = SQLiteQueue(self.db_path)
        created = store.append_audit_event(
            record_id="rec-1",
            event_type="material_submitted",
            event_key="submission:1",
            summary={"round": 1},
        )
        duplicate = store.append_audit_event(
            record_id="rec-1",
            event_type="material_submitted",
            event_key="submission:1",
            summary={"round": 2},
        )
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(store.list_audit_events("rec-1")[0]["summary"], {"round": 1})

    def test_missing_or_non_boolean_feature_flags_are_off(self):
        original = sys.modules.get("config")
        config = types.ModuleType("config")
        config.ADSURE_OPS_ENABLED = "true"
        sys.modules["config"] = config
        try:
            self.assertFalse(feature_flags.ops_enabled())
            self.assertFalse(feature_flags.audit_timeline_enabled())
            config.ADSURE_OPS_ENABLED = True
            self.assertTrue(feature_flags.ops_enabled())
        finally:
            if original is None:
                sys.modules.pop("config", None)
            else:
                sys.modules["config"] = original


if __name__ == "__main__":
    unittest.main()
