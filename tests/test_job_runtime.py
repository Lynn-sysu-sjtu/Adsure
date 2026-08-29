import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock


def _ensure_import_stubs():
    if "config" not in sys.modules:
        config = types.ModuleType("config")
        config.FEISHU_APP_ID = "test-app"
        config.FEISHU_APP_SECRET = "test-secret"
        config.BITABLE_APP_TOKEN = "test-base"
        config.BITABLE_TABLE_ID = "test-table"
        config.WORKBENCH_URL = "https://workbench.example.test"
        config.LEGAL_DEPT_NAME = "法律与合规"
        config.LEGAL_OPEN_IDS = []
        sys.modules["config"] = config
    if "requests" not in sys.modules:
        requests = types.ModuleType("requests")
        requests.post = requests.get = requests.put = lambda *_args, **_kwargs: None
        sys.modules["requests"] = requests


_ensure_import_stubs()

import feishu_api
from card_action_service import CardActionRequest, handle_card_action
from error_handling import OperationError
from fields_v4 import (
    F_提交人, F_流转_当前状态, F_流转_反馈类型,
    F_法务_AI意见评价, F_法务_物料裁决, F_法务_复核时间,
)
from job_runtime import QueueProcessor
from reliable_queue import SUCCEEDED, TERMINAL_FAILED, SQLiteQueue


class JobRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteQueue(
            str(Path(self.tmp.name) / "runtime.sqlite3"),
            retry_base_seconds=0,
            retry_max_seconds=0,
        )
        self.processor = QueueProcessor(self.store, worker_id="test-worker")
        self.record = {"fields": {
            F_提交人: [{"id": "ou-operator", "name": "运营"}],
            F_流转_当前状态: "运营起草",
        }}

    def tearDown(self):
        self.tmp.cleanup()

    def _predictor(self, execute):
        module = types.ModuleType("predictor")
        module.execute = execute
        return mock.patch.dict(sys.modules, {"predictor": module})

    def test_transient_review_failure_twice_then_success_is_user_silent(self):
        effects = [
            OperationError("transient_network", retryable=True),
            OperationError("transient_network", retryable=True),
            ("待运营修改", {}),
        ]
        job = self.store.enqueue_job(
            "ai_review", "rec-1", "review-1",
            {"mode": "标准", "operator_id": "ou-operator", "round": 1}, max_attempts=3,
        )
        with self._predictor(mock.Mock(side_effect=effects)), \
                mock.patch.object(feishu_api, "update_record"), \
                mock.patch.object(feishu_api, "get_record", return_value=self.record):
            self.processor.run_once()
            self.processor.run_once()
            self.processor.run_once()

        stored = self.store.get_job(job.item_id)
        self.assertEqual(stored["status"], SUCCEEDED)
        self.assertEqual(stored["attempts"], 3)
        deliveries = self.store.list_deliveries()
        self.assertEqual([item["card_type"] for item in deliveries], ["operator_result"])

    def test_legal_partial_delivery_retries_only_failed_recipient(self):
        self.store.enqueue_job(
            "route_to_legal", "rec-1", "legal-1",
            {"source": "skip_review", "round": 1}, max_attempts=3,
        )
        sent_recipients = []

        def send(recipient, _card, **_kwargs):
            sent_recipients.append(recipient)
            if recipient == "ou-2" and sent_recipients.count("ou-2") == 1:
                raise OperationError("transient_network", retryable=True)
            return {"success": True, "message_id": f"msg-{recipient}"}

        with mock.patch.object(feishu_api, "update_record") as update, \
                mock.patch.object(feishu_api, "get_dept_open_ids", return_value=["ou-1", "ou-2"]), \
                mock.patch.object(feishu_api, "get_record", return_value=self.record), \
                mock.patch.object(feishu_api, "send_card", side_effect=send):
            self.processor.run_once()  # create two delivery rows
            self.processor.run_once()  # ou-1 succeeds
            self.processor.run_once()  # ou-2 fails
            self.processor.run_once()  # only ou-2 retries

        self.assertEqual(sent_recipients, ["ou-1", "ou-2", "ou-2"])
        rows = {row["recipient_id"]: row for row in self.store.list_deliveries()}
        self.assertEqual(rows["ou-1"]["attempts"], 1)
        self.assertEqual(rows["ou-2"]["attempts"], 2)
        self.assertTrue(all(row["status"] == SUCCEEDED for row in rows.values()))
        self.assertEqual(update.call_args_list[0].args[1][F_流转_当前状态], "待法务复核")
        self.assertNotIn("运营起草", [call.args[1].get(F_流转_当前状态) for call in update.call_args_list])

    def test_ambiguous_send_retries_with_same_uuid_and_one_delivery_row(self):
        self.store.enqueue_delivery(
            job_id=None, business_action="initial", record_id="rec-1",
            recipient_id="ou-operator", card_type="initial_review",
            idempotency_key="delivery-stable", max_attempts=2,
        )
        uuids = []

        def send(_recipient, _card, *, idempotency_uuid):
            uuids.append(idempotency_uuid)
            if len(uuids) == 1:
                raise OperationError("transient_network", retryable=True)
            return {"success": True, "message_id": "msg-1"}

        with mock.patch.object(feishu_api, "get_record", return_value=self.record), \
                mock.patch.object(feishu_api, "send_card", side_effect=send):
            self.processor.run_once()
            self.processor.run_once()

        rows = self.store.list_deliveries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], SUCCEEDED)
        self.assertEqual(uuids[0], uuids[1])

    def test_permanent_delivery_error_stops_without_infinite_retry(self):
        self.store.enqueue_delivery(
            job_id=None, business_action="legal", record_id="rec-1",
            recipient_id="ou-invalid", card_type="legal_review",
            idempotency_key="permanent", max_attempts=5,
        )
        with mock.patch.object(feishu_api, "get_record", return_value=self.record), \
                mock.patch.object(feishu_api, "send_card", side_effect=OperationError(
                    "permission_denied", retryable=False,
                )) as send:
            self.processor.run_once()
            self.assertFalse(self.processor.run_once())
        row = self.store.list_deliveries()[0]
        self.assertEqual(row["status"], TERMINAL_FAILED)
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(send.call_count, 1)

    def test_ambiguous_legal_write_is_confirmed_before_retry(self):
        payload = {
            "ai_opinion": "同意无补充",
            "verdict": "通过",
            "reviewer_name": "法务",
            "notify_operator": False,
            "submitted_at_ms": 1700000000000,
            "request_hash": "request-hash",
        }
        queued = self.store.enqueue_job(
            "legal_review", "rec-1", "legal-review:key", payload, max_attempts=2,
        )
        after_fields = {
            F_提交人: self.record["fields"][F_提交人],
            F_法务_AI意见评价: "同意无补充",
            F_法务_物料裁决: "通过",
            F_流转_当前状态: "已通过",
            F_流转_反馈类型: "无",
            F_法务_复核时间: 1700000000000,
        }
        records = [self.record, {"fields": after_fields}]
        with mock.patch.object(feishu_api, "get_record", side_effect=records), \
                mock.patch.object(feishu_api, "update_record", side_effect=OperationError(
                    "transient_network", retryable=True,
                )) as update, \
                mock.patch.object(self.processor, "_save_correction_noncritical"):
            self.processor.run_once()
            self.processor.run_once()

        self.assertEqual(self.store.get_job(queued.item_id)["status"], SUCCEEDED)
        self.assertEqual(update.call_count, 1)

    def test_legal_review_queues_operator_verdict_after_writeback(self):
        payload = {
            "ai_opinion": "同意无补充",
            "verdict": "通过",
            "reviewer_name": "法务",
            "notify_operator": True,
            "submitted_at_ms": 1700000000000,
            "request_hash": "request-hash",
        }
        queued = self.store.enqueue_job(
            "legal_review", "rec-1", "legal-review:notify", payload, max_attempts=2,
        )
        with mock.patch.object(feishu_api, "get_record", return_value=self.record), \
                mock.patch.object(feishu_api, "update_record") as update, \
                mock.patch.object(self.processor, "_save_correction_noncritical"):
            self.processor.run_once()

        self.assertEqual(self.store.get_job(queued.item_id)["status"], SUCCEEDED)
        self.assertEqual(update.call_args.args[1][F_流转_当前状态], "已通过")
        deliveries = self.store.list_deliveries()
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["recipient_id"], "ou-operator")
        self.assertEqual(deliveries[0]["card_type"], "verdict")

    def test_stale_first_attempt_does_not_update_or_create_delivery(self):
        queued = self.store.enqueue_job(
            "route_to_legal", "rec-stale", "old-skip-action",
            {"source": "skip_review", "action": "skip_review", "round": 1},
        )
        stale_record = {"fields": {
            F_提交人: self.record["fields"][F_提交人],
            F_流转_当前状态: "待运营修改",
        }}
        with mock.patch.object(feishu_api, "get_record", return_value=stale_record), \
                mock.patch.object(feishu_api, "update_record") as update, \
                mock.patch.object(feishu_api, "get_dept_open_ids") as recipients:
            self.processor.run_once()

        stored = self.store.get_job(queued.item_id)
        self.assertEqual(stored["status"], SUCCEEDED)
        self.assertEqual(stored["result"], {"ignored": "stale_action"})
        update.assert_not_called()
        recipients.assert_not_called()
        self.assertEqual(self.store.list_deliveries(), [])

    def test_jobs_and_deliveries_are_processed_fairly_and_without_idle_wait(self):
        for index in range(2):
            self.store.enqueue_job("noop", f"rec-job-{index}", f"job-{index}")
        self.store.enqueue_delivery(
            job_id=None, business_action="test", record_id="rec-delivery",
            recipient_id="ou-test", card_type="initial_review", idempotency_key="delivery-0",
        )
        order = []
        with mock.patch.object(self.processor, "_run_job", side_effect=lambda _item: order.append("job")), \
                mock.patch.object(self.processor, "_run_delivery", side_effect=lambda _item: order.append("delivery")):
            self.processor.run_once()
            self.processor.run_once()
            self.processor.run_once()
        self.assertEqual(order, ["job", "delivery", "job"])

        for index in range(2, 4):
            self.store.enqueue_job("noop", f"rec-job-{index}", f"job-{index}")
        jobs_only = []
        with mock.patch.object(self.processor, "_run_job", side_effect=lambda _item: jobs_only.append("job")):
            self.processor.run_once()
            self.processor.run_once()
        self.assertEqual(jobs_only, ["job", "job"])

        for index in range(1, 3):
            self.store.enqueue_delivery(
                job_id=None, business_action="test", record_id=f"rec-delivery-{index}",
                recipient_id="ou-test", card_type="initial_review",
                idempotency_key=f"delivery-{index}",
            )
        deliveries_only = []
        with mock.patch.object(
            self.processor, "_run_delivery", side_effect=lambda _item: deliveries_only.append("delivery"),
        ):
            self.processor.run_once()
            self.processor.run_once()
        self.assertEqual(deliveries_only, ["delivery", "delivery"])

    def test_terminal_review_failure_creates_one_minimal_notice(self):
        self.store.enqueue_job(
            "ai_review", "rec-1", "review-terminal",
            {"mode": "标准", "operator_id": "ou-operator", "round": 1}, max_attempts=1,
        )
        sent_cards = []

        def send(_recipient, card, **_kwargs):
            sent_cards.append(card)
            return {"success": True, "message_id": "msg-failure"}

        with self._predictor(mock.Mock(side_effect=RuntimeError("SECRET_EXCEPTION_123"))), \
                mock.patch.object(feishu_api, "update_record"), \
                mock.patch.object(feishu_api, "get_record", return_value=self.record), \
                mock.patch.object(feishu_api, "send_card", side_effect=send):
            self.processor.run_once()  # review terminal -> recovery job
            self.processor.run_once()  # recovery -> one notice delivery
            self.processor.run_once()  # notice succeeds
            self.assertFalse(self.processor.run_once())

        self.assertEqual(len(sent_cards), 1)
        rendered = repr(sent_cards[0])
        self.assertIn("暂时没有处理完成", rendered)
        self.assertIn("请稍后再试一次", rendered)
        self.assertNotIn("SECRET_EXCEPTION_123", rendered)
        self.assertEqual(
            [row["card_type"] for row in self.store.list_deliveries()], ["final_failure"],
        )
        retry_action = sent_cards[0]["elements"][-1]["actions"][0]["value"]
        self.assertEqual(retry_action["round"], 2)
        retried = handle_card_action(CardActionRequest(
            action=retry_action["action"], record_id="rec-1",
            event_id="evt-user-retry", round=retry_action["round"],
        ), store=self.store)
        self.assertTrue(retried.created)
        self.assertEqual(self.store.get_job(retried.job_id)["job_type"], "ai_review")

    def test_recovered_review_uses_existing_writeback_instead_of_running_twice(self):
        queued = self.store.enqueue_job(
            "ai_review", "rec-1", "review-recovered",
            {"mode": "标准", "operator_id": "ou-operator", "round": 1}, max_attempts=2,
        )
        interrupted = self.store.claim_job("dead-worker")
        self.store.fail_job(interrupted["id"], retryable=True, category="worker_interrupted")
        completed_record = {"fields": {
            **self.record["fields"], F_流转_当前状态: "待运营修改",
        }}
        execute = mock.Mock(return_value=("待运营修改", {}))
        with self._predictor(execute), \
                mock.patch.object(feishu_api, "get_record", return_value=completed_record), \
                mock.patch.object(feishu_api, "update_record"):
            self.processor.run_once()

        self.assertEqual(self.store.get_job(queued.item_id)["status"], SUCCEEDED)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
