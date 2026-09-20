import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import uuid
from unittest import mock


if "config" not in sys.modules:
    sys.modules["config"] = types.ModuleType("config")
config = sys.modules["config"]

import ops_delivery_service
import ops_routes
from reliable_queue import SQLiteQueue


class OpsDeliveryServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteQueue(
            os.path.join(self.tmp.name, "ops.sqlite3"),
            retry_base_seconds=0,
            retry_max_seconds=0,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _delivery(
        self, key, *, card_type="initial_review", record_id="rec-1", payload=None
    ):
        return self.store.enqueue_delivery(
            job_id=None,
            business_action="initial_review_card",
            record_id=record_id,
            recipient_id=f"ou-secret-{key}",
            card_type=card_type,
            idempotency_key=key,
            payload=payload or {},
            max_attempts=2,
        )

    def _terminal(self, key="delivery-terminal", **kwargs):
        queued = self._delivery(key, **kwargs)
        claimed = self.store.claim_delivery("worker-secret")
        self.store.fail_delivery(
            claimed["id"], retryable=False, category="permission_denied"
        )
        return queued

    def test_filters_pagination_and_redaction_start_at_sql_boundary(self):
        self._terminal(
            "IDEMPOTENCY_SECRET",
            record_id="rec-alpha",
            payload={"private": "PAYLOAD_SECRET"},
        )
        succeeded = self._delivery(
            "delivery-success",
            card_type="operator_result",
            record_id="rec-beta",
        )
        claimed = self.store.claim_delivery("worker")
        self.assertEqual(claimed["id"], succeeded.item_id)
        self.store.complete_delivery(claimed["id"], "MESSAGE_SECRET")
        self._delivery("delivery-pending", record_id="rec-gamma")

        page = ops_delivery_service.list_deliveries(self.store, page=1, page_size=2)
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["items"]), 2)
        serialized = json.dumps(page, ensure_ascii=False)
        for secret in (
            "PAYLOAD_SECRET",
            "IDEMPOTENCY_SECRET",
            "MESSAGE_SECRET",
            "worker-secret",
            "permission_denied",
            "payload",
            "idempotency",
            "error_category",
        ):
            self.assertNotIn(secret, serialized)

        filtered = ops_delivery_service.list_deliveries(
            self.store,
            status="succeeded",
            card_type="operator_result",
            record_query="rec-beta",
        )
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["card_type"], "运营审核结果卡")
        self.assertTrue(filtered["items"][0]["recipient"].startswith("id#"))
        self.assertTrue(filtered["items"][0]["message"].startswith("msg#"))

    def test_replay_reuses_same_row_key_payload_and_stable_uuid(self):
        queued = self._terminal(payload={"round": 1, "private": "keep-this-payload"})
        before = self.store.get_delivery_by_key("delivery-terminal")
        stable_before = uuid.uuid5(uuid.NAMESPACE_URL, before["idempotency_key"])

        first = ops_delivery_service.replay_delivery(self.store, queued.item_id)
        second = ops_delivery_service.replay_delivery(self.store, queued.item_id)
        after = self.store.get_delivery_by_key("delivery-terminal")
        stable_after = uuid.uuid5(uuid.NAMESPACE_URL, after["idempotency_key"])

        self.assertEqual(first, {"result": "replayed", "message": "已重新安排发送"})
        self.assertEqual(
            second, {"result": "updated", "message": "状态已更新，请刷新查看"}
        )
        self.assertEqual(len(self.store.list_deliveries()), 1)
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["payload"], before["payload"])
        self.assertEqual(after["max_attempts"], before["max_attempts"])
        self.assertEqual(after["idempotency_key"], before["idempotency_key"])
        self.assertEqual(stable_after, stable_before)
        self.assertEqual(after["status"], "pending")
        self.assertEqual(after["attempts"], 0)
        self.assertIsNone(after["lease_until"])
        self.assertIsNone(after["worker_id"])
        self.assertIsNone(after["error_category"])
        self.assertEqual(after["replay_count"], 1)
        events = self.store.list_audit_events("rec-1")
        self.assertEqual(
            events[0]["event_key"], f"delivery_replayed:{queued.item_id}:1"
        )

    def test_only_terminal_without_message_can_replay(self):
        pending = self._delivery("pending")
        running = self._delivery("running")
        retryable = self._delivery("retryable")
        succeeded = self._delivery("succeeded")
        terminal_with_message = self._delivery("terminal-with-message")
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE deliveries SET status = 'running', lease_until = 9999999999 WHERE id = ?",
                (running.item_id,),
            )
            conn.execute(
                """UPDATE deliveries SET status = 'retryable_failed',
                   next_attempt_at = 9999999999 WHERE id = ?""",
                (retryable.item_id,),
            )
            conn.execute(
                "UPDATE deliveries SET status = 'succeeded', message_id = 'msg-success' WHERE id = ?",
                (succeeded.item_id,),
            )
            conn.execute(
                """UPDATE deliveries SET status = 'terminal_failed',
                   message_id = 'msg-existing' WHERE id = ?""",
                (terminal_with_message.item_id,),
            )

        for item_id in (
            pending.item_id,
            running.item_id,
            retryable.item_id,
            succeeded.item_id,
            terminal_with_message.item_id,
            999999,
        ):
            with self.subTest(item_id=item_id):
                result = ops_delivery_service.replay_delivery(self.store, item_id)
                self.assertEqual(result["result"], "unavailable")
                self.assertEqual(result["message"], "暂时无法处理")

    def test_frontend_uses_safe_dom_and_fixed_response_copy(self):
        source = Path("static/ops_deliveries.js").read_text(encoding="utf-8")
        template = Path("templates/ops_deliveries.html").read_text(encoding="utf-8")
        self.assertIn("textContent", source)
        self.assertNotIn("innerHTML", source)
        self.assertNotIn("data.message", source)
        self.assertNotIn("alert(", source)
        self.assertNotIn("ADSURE_OPS_PASSWORD", source + template)
        self.assertIn("await load(page, resultMessage)", source)


class OpsRoutesTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            name: getattr(config, name, None)
            for name in (
                "ADSURE_OPS_ENABLED",
                "ADSURE_OPS_USERNAME",
                "ADSURE_OPS_PASSWORD",
            )
        }

    def tearDown(self):
        for name, value in self.original.items():
            if value is None:
                try:
                    delattr(config, name)
                except AttributeError:
                    pass
            else:
                setattr(config, name, value)

    def _configure(self, enabled=True, username="maintainer", password="secret"):
        config.ADSURE_OPS_ENABLED = enabled
        config.ADSURE_OPS_USERNAME = username
        config.ADSURE_OPS_PASSWORD = password

    def test_disabled_or_incomplete_configuration_is_404_before_storage(self):
        requests = [
            (False, "maintainer", "secret"),
            (True, "", "secret"),
            (True, "maintainer", ""),
        ]
        for enabled, username, password in requests:
            with self.subTest(
                enabled=enabled, username=username, password=bool(password)
            ):
                self._configure(enabled, username, password)
                with mock.patch("ops_routes.get_store") as store:
                    self.assertEqual(ops_routes.ops_delivery_list(), ("", 404))
                    self.assertEqual(ops_routes.ops_delivery_replay(1), ("", 404))
                    self.assertEqual(ops_routes.ops_deliveries_page(), ("", 404))
                store.assert_not_called()

    def test_wrong_credentials_rejected_and_correct_credentials_work(self):
        self._configure()
        wrong_request = types.SimpleNamespace(
            authorization=types.SimpleNamespace(
                username="maintainer", password="wrong"
            ),
            args={},
        )
        with mock.patch("ops_routes._request", return_value=wrong_request):
            response = ops_routes.ops_deliveries_page()
        self.assertEqual(response[1], 401)
        self.assertIn("Basic", response[2]["WWW-Authenticate"])

        correct_request = types.SimpleNamespace(
            authorization=types.SimpleNamespace(
                username="maintainer", password="secret"
            ),
            args={"page": "1"},
        )
        with mock.patch(
            "ops_routes._request", return_value=correct_request
        ), mock.patch(
            "ops_routes._render_template", return_value="OPS_PAGE"
        ), mock.patch(
            "ops_routes.get_store"
        ) as store, mock.patch(
            "ops_routes.list_deliveries", return_value={"items": []}
        ), mock.patch(
            "ops_routes._jsonify", side_effect=lambda value: value
        ):
            self.assertEqual(ops_routes.ops_deliveries_page(), "OPS_PAGE")
            self.assertEqual(ops_routes.ops_delivery_list(), {"items": []})
        store.assert_called_once()

    def test_list_failure_returns_only_generic_copy(self):
        self._configure()
        request = types.SimpleNamespace(
            authorization=types.SimpleNamespace(
                username="maintainer", password="secret"
            ),
            args={},
        )
        with mock.patch("ops_routes._request", return_value=request), mock.patch(
            "ops_routes.get_store"
        ), mock.patch(
            "ops_routes.list_deliveries",
            side_effect=RuntimeError("SECRET_SQL_DETAIL"),
        ), mock.patch(
            "ops_routes._jsonify", side_effect=lambda value: value
        ):
            payload, status = ops_routes.ops_delivery_list()
        self.assertEqual(status, 503)
        self.assertEqual(payload, {"items": [], "message": "暂时无法处理"})
        self.assertNotIn("SECRET_SQL_DETAIL", json.dumps(payload, ensure_ascii=False))

    def test_replay_storage_failure_returns_only_generic_copy(self):
        self._configure()
        request = types.SimpleNamespace(
            authorization=types.SimpleNamespace(
                username="maintainer", password="secret"
            ),
            args={},
        )
        with mock.patch("ops_routes._request", return_value=request), mock.patch(
            "ops_routes.get_store", side_effect=RuntimeError("SECRET_DB_PATH")
        ), mock.patch("ops_routes._jsonify", side_effect=lambda value: value):
            payload, status = ops_routes.ops_delivery_replay(1)
        self.assertEqual(status, 503)
        self.assertEqual(payload, {"result": "unavailable", "message": "暂时无法处理"})
        self.assertNotIn("SECRET_DB_PATH", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
