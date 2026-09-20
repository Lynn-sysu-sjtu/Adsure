import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


def _install_import_stubs():
    if "config" not in sys.modules:
        config = types.ModuleType("config")
        config.FEISHU_APP_ID = "test-app"
        config.FEISHU_APP_SECRET = "test-secret"
        config.BITABLE_APP_TOKEN = "test-base"
        config.BITABLE_TABLE_ID = "test-table"
        config.WORKBENCH_URL = "https://workbench.example.test"
        config.LEGAL_DEPT_NAME = "法律与合规"
        config.LEGAL_OPEN_IDS = []
        config.ADSURE_DELIVERY_MAX_ATTEMPTS = 2
        sys.modules["config"] = config
    if "requests" not in sys.modules:
        requests = types.ModuleType("requests")
        requests.post = requests.get = requests.put = requests.patch = (
            lambda *_args, **_kwargs: None
        )
        sys.modules["requests"] = requests


_install_import_stubs()

import feishu_api
import legal_card_sync
from error_handling import OperationError
from fields_v4 import (
    F_提交人,
    F_审核_审核意见,
    F_法务_AI意见评价,
    F_法务_批注,
    F_法务_物料裁决,
    F_法务_复核时间,
    F_流转_当前状态,
    F_流转_反馈类型,
    F_流转_驳回次数,
)
from job_runtime import QueueProcessor
from reliable_queue import SUCCEEDED, TERMINAL_FAILED, SQLiteQueue
from review_service import (
    build_update_fields,
    review_may_apply,
    review_version,
)


class LegalCardSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteQueue(
            os.path.join(self.tmp.name, "legal.sqlite3"),
            retry_base_seconds=0,
            retry_max_seconds=0,
        )
        self.processor = QueueProcessor(self.store, worker_id="legal-test")

    def tearDown(self):
        self.tmp.cleanup()

    def _sent_legal(self, recipient, key, message_id, payload=None):
        self.store.enqueue_delivery(
            job_id=None,
            business_action="legal_review_notification",
            record_id="rec-legal",
            recipient_id=recipient,
            card_type="legal_review",
            idempotency_key=key,
            payload=payload,
        )
        claimed = self.store.claim_delivery("setup")
        self.store.complete_delivery(claimed["id"], message_id)

    def _payload(self, **overrides):
        payload = {
            "ai_opinion": "同意无补充",
            "verdict": "通过",
            "reviewer_name": "法务甲",
            "objection_fields": [],
            "supplement_reason": "",
            "reject_reason": "",
            "correct_judgment": "",
            "final_suggestion": "",
            "note": "",
            "notify_operator": False,
            "submitted_at_ms": 1700000000000,
            "request_hash": "request-one",
        }
        payload.update(overrides)
        return payload

    def test_same_round_cards_schedule_independent_updates_once(self):
        self._sent_legal(
            "ou-one",
            "legal:rec-legal:round:1:recipient:one",
            "msg-one",
            {"round": 1},
        )
        self._sent_legal(
            "ou-two",
            "legal:rec-legal:round:1:recipient:two",
            "msg-two",
            {},
        )
        self._sent_legal(
            "ou-old",
            "legal:rec-legal:round:2:recipient:old",
            "msg-old",
            {"round": 2},
        )
        review_job = self.store.enqueue_job(
            "legal_review", "rec-legal", "legal-review:sync-one", self._payload()
        )
        job = {"id": review_job.item_id, "record_id": "rec-legal"}
        with mock.patch(
            "legal_card_sync.legal_card_sync_enabled", return_value=True
        ):
            first = legal_card_sync.schedule_legal_card_updates(
                self.store, job, 1, self._payload()
            )
            second = legal_card_sync.schedule_legal_card_updates(
                self.store, job, 1, self._payload()
            )

        updates = [
            row
            for row in self.store.list_deliveries()
            if row["card_type"] == "legal_card_update"
        ]
        self.assertEqual(first, 2)
        self.assertEqual(second, 2)
        self.assertEqual(len(updates), 2)
        self.assertEqual(
            {row["payload"]["target_message_id"] for row in updates},
            {"msg-one", "msg-two"},
        )
        self.assertTrue(all(row["payload"]["round"] == 1 for row in updates))
        internal = self.store.list_audit_events("rec-legal")
        self.assertEqual(
            [row["event_type"] for row in internal],
            ["legal_cards_sync_scheduled"],
        )

        with mock.patch(
            "legal_card_sync.legal_card_sync_enabled", return_value=True
        ):
            edit_job = self.store.enqueue_job(
                "legal_review", "rec-legal", "legal-review:sync-edit", self._payload()
            )
            legal_card_sync.schedule_legal_card_updates(
                self.store,
                {"id": edit_job.item_id, "record_id": "rec-legal"},
                1,
                self._payload(),
            )
        updates = [
            row
            for row in self.store.list_deliveries()
            if row["card_type"] == "legal_card_update"
        ]
        self.assertEqual(len(updates), 4)

    def test_disabled_sync_creates_no_update(self):
        self._sent_legal(
            "ou-one",
            "legal:rec-legal:round:1:recipient:one",
            "msg-one",
            {"round": 1},
        )
        with mock.patch(
            "legal_card_sync.legal_card_sync_enabled", return_value=False
        ), mock.patch.object(
            self.store, "list_succeeded_legal_deliveries"
        ) as listed:
            count = legal_card_sync.schedule_legal_card_updates(
                self.store,
                {"id": 1, "record_id": "rec-legal"},
                1,
                self._payload(),
            )
        self.assertEqual(count, 0)
        listed.assert_not_called()

    def test_notify_operator_false_still_schedules_current_legal_cards(self):
        for suffix in ("one", "two"):
            self._sent_legal(
                f"ou-{suffix}",
                f"legal:rec-legal:round:1:recipient:{suffix}",
                f"msg-{suffix}",
                {"round": 1},
            )
        waiting = {
            F_流转_当前状态: "待法务复核",
            F_审核_审核意见: "AI 意见",
            F_提交人: [{"id": "ou-operator", "name": "运营"}],
        }
        payload = self._payload(
            review_intent="initial",
            expected_review_version=review_version(waiting),
            notify_operator=False,
        )
        queued = self.store.enqueue_job(
            "legal_review", "rec-legal", "legal-review:notify-false", payload
        )
        with mock.patch(
            "legal_card_sync.legal_card_sync_enabled", return_value=True
        ), mock.patch.object(
            feishu_api, "get_record", return_value={"fields": waiting}
        ), mock.patch.object(feishu_api, "update_record"), mock.patch.object(
            self.processor, "_save_correction_noncritical"
        ), mock.patch.object(feishu_api, "send_card") as send:
            self.processor._run_job(self.store.claim_job("legal-review-worker"))
        self.assertEqual(self.store.get_job(queued.item_id)["status"], SUCCEEDED)
        updates = [
            row
            for row in self.store.list_deliveries()
            if row["card_type"] == "legal_card_update"
        ]
        self.assertEqual(len(updates), 2)
        send.assert_not_called()

    def test_sync_entry_failure_does_not_rollback_legal_review(self):
        waiting = {
            F_流转_当前状态: "待法务复核",
            F_审核_审核意见: "AI 意见",
            F_提交人: [{"id": "ou-operator", "name": "运营"}],
        }
        payload = self._payload(
            review_intent="initial",
            expected_review_version=review_version(waiting),
            notify_operator=False,
        )
        queued = self.store.enqueue_job(
            "legal_review", "rec-sync-boundary", "legal-review:sync-boundary", payload
        )

        with mock.patch.object(
            feishu_api, "get_record", return_value={"fields": waiting}
        ), mock.patch.object(
            feishu_api, "update_record"
        ) as update, mock.patch.object(
            self.processor, "_save_correction_noncritical"
        ), mock.patch(
            "legal_card_sync.schedule_legal_card_updates",
            side_effect=RuntimeError("SECRET_SYNC"),
        ):
            self.processor.run_once()

        self.assertEqual(self.store.get_job(queued.item_id)["status"], SUCCEEDED)
        update.assert_called_once()
        self.assertEqual(self.store.list_deliveries(), [])

    def test_update_failures_are_isolated_per_card(self):
        for index in (1, 2):
            self.store.enqueue_delivery(
                job_id=None,
                business_action="legal_card_completed_update",
                record_id="rec-legal",
                recipient_id=f"ou-{index}",
                card_type="legal_card_update",
                idempotency_key=f"update-{index}",
                payload={
                    "target_message_id": f"msg-{index}",
                    "reviewer_name": "法务甲",
                    "verdict": "通过",
                    "round": 1,
                },
                max_attempts=1,
            )
        effects = [
            OperationError("permission_denied", retryable=False),
            {"success": True, "message_id": "msg-2", "code": 0},
        ]
        with mock.patch.object(
            feishu_api, "update_card", side_effect=effects
        ), mock.patch.object(feishu_api, "get_record") as get_record, mock.patch.object(
            feishu_api, "send_card"
        ) as send:
            self.processor.run_once()
            self.processor.run_once()
        rows = self.store.list_deliveries()
        self.assertEqual(rows[0]["status"], TERMINAL_FAILED)
        self.assertEqual(rows[1]["status"], SUCCEEDED)
        get_record.assert_not_called()
        send.assert_not_called()

    def test_delayed_legal_card_sends_completed_state(self):
        self.store.enqueue_delivery(
            job_id=None,
            business_action="legal_review_notification",
            record_id="rec-legal",
            recipient_id="ou-legal",
            card_type="legal_review",
            idempotency_key="legal:rec-legal:round:1:recipient:late",
            payload={"round": 1},
        )
        fields = {
            F_流转_当前状态: "已通过",
            F_法务_物料裁决: "通过",
        }
        sent = []
        with mock.patch(
            "legal_card_sync.legal_card_sync_enabled", return_value=True
        ), mock.patch.object(
            feishu_api, "get_record", return_value={"fields": fields}
        ), mock.patch.object(
            feishu_api,
            "send_card",
            side_effect=lambda _recipient, card, **_kwargs: sent.append(card)
            or {"success": True, "message_id": "msg-late", "code": 0},
        ):
            self.processor.run_once()
        self.assertEqual(
            sent[0]["header"]["title"]["content"],
            "✅ 该物料已完成法务复核",
        )
        self.assertEqual(len(sent[0]["elements"][-1]["actions"]), 1)

    def test_delayed_sync_hook_failure_falls_back_to_original_legal_card(self):
        self.store.enqueue_delivery(
            job_id=None,
            business_action="legal_review_notification",
            record_id="rec-legal",
            recipient_id="ou-legal",
            card_type="legal_review",
            idempotency_key="legal:rec-legal:round:1:recipient:fallback",
            payload={"round": 1},
        )
        fields = {F_流转_当前状态: "待法务复核"}
        sent = []
        with mock.patch.object(
            feishu_api, "get_record", return_value={"fields": fields}
        ), mock.patch(
            "legal_card_sync.completed_card_for_delayed_delivery",
            side_effect=RuntimeError("SECRET_OPTIONAL_HOOK"),
        ), mock.patch.object(
            feishu_api,
            "send_card",
            side_effect=lambda _recipient, card, **_kwargs: sent.append(card)
            or {"success": True, "message_id": "msg-fallback", "code": 0},
        ):
            self.processor.run_once()

        delivery = self.store.list_deliveries()[0]
        self.assertEqual(delivery["status"], SUCCEEDED)
        self.assertEqual(delivery["message_id"], "msg-fallback")
        self.assertEqual(sent[0]["header"]["title"]["content"], "📨 新物料待法务复核")

    def test_stale_version_has_no_business_side_effects(self):
        waiting = {
            F_流转_当前状态: "待法务复核",
            F_审核_审核意见: "AI 初始意见",
            F_流转_驳回次数: 3,
        }
        payload = self._payload(
            ai_opinion="驳回",
            verdict="不通过",
            objection_fields=["风险等级"],
            reject_reason="理由",
            correct_judgment="正确",
            final_suggestion="修改",
            review_intent="initial",
            expected_review_version=review_version(waiting),
        )
        current = {
            **waiting,
            F_流转_当前状态: "已通过",
            F_法务_AI意见评价: "同意无补充",
            F_法务_物料裁决: "通过",
            F_流转_反馈类型: "无",
            F_法务_复核时间: 1699999999000,
        }
        queued = self.store.enqueue_job(
            "legal_review", "rec-stale", "legal-review:stale", payload
        )
        with mock.patch.object(
            feishu_api, "get_record", return_value={"fields": current}
        ), mock.patch.object(feishu_api, "update_record") as update, mock.patch.object(
            self.processor, "_save_correction_noncritical"
        ) as save, mock.patch.object(
            self.processor, "_sync_legal_cards"
        ) as sync, mock.patch.object(
            self.processor, "_record_audit", create=True
        ) as audit:
            self.processor.run_once()
        stored = self.store.get_job(queued.item_id)
        self.assertEqual(stored["status"], SUCCEEDED)
        self.assertEqual(stored["result"], {"stale": True})
        self.assertEqual(current[F_流转_驳回次数], 3)
        update.assert_not_called()
        save.assert_not_called()
        sync.assert_not_called()
        audit.assert_not_called()
        self.assertEqual(self.store.list_deliveries(), [])

    def test_same_millisecond_other_reviewer_is_stale_without_side_effects(self):
        waiting = {
            F_流转_当前状态: "待法务复核",
            F_审核_审核意见: "AI 初始意见",
        }
        first = self._payload(
            reviewer_name="法务甲",
            note="甲的意见",
            review_intent="initial",
            expected_review_version=review_version(waiting),
        )
        current = {**waiting, **build_update_fields(first, waiting)}
        self.assertEqual(current[F_法务_批注], "【法务：法务甲】\n甲的意见")

        later = self._payload(
            reviewer_name="法务乙",
            note="乙的意见",
            review_intent="initial",
            expected_review_version=review_version(waiting),
        )
        queued = self.store.enqueue_job(
            "legal_review", "rec-stale-reviewer", "legal-review:stale-reviewer", later
        )
        with mock.patch.object(
            feishu_api, "get_record", return_value={"fields": current}
        ), mock.patch.object(feishu_api, "update_record") as update, mock.patch.object(
            self.processor, "_save_correction_noncritical"
        ) as save, mock.patch.object(
            self.processor, "_sync_legal_cards"
        ) as sync, mock.patch.object(
            self.processor, "_record_audit", create=True
        ) as audit:
            self.processor.run_once()

        stored = self.store.get_job(queued.item_id)
        self.assertEqual(stored["status"], SUCCEEDED)
        self.assertEqual(stored["result"], {"stale": True})
        update.assert_not_called()
        save.assert_not_called()
        sync.assert_not_called()
        audit.assert_not_called()
        self.assertEqual(self.store.list_deliveries(), [])

    def test_edit_and_ambiguous_retry_keep_existing_semantics(self):
        terminal = {
            F_流转_当前状态: "需修改",
            F_审核_审核意见: "AI 意见",
            F_法务_AI意见评价: "同意无补充",
            F_法务_物料裁决: "不通过",
            F_流转_反馈类型: "无",
            F_法务_复核时间: 1600000000000,
        }
        edit = self._payload(
            review_intent="edit",
            expected_review_version=review_version(terminal),
            submitted_at_ms=1700000000100,
        )
        self.assertTrue(review_may_apply(terminal, edit))
        self.assertTrue(review_may_apply(terminal, self._payload()))
        self.store.enqueue_job(
            "legal_review", "rec-edit", "legal-review:edit", edit
        )
        with mock.patch.object(
            feishu_api, "get_record", return_value={"fields": terminal}
        ), mock.patch.object(feishu_api, "update_record") as update, mock.patch.object(
            self.processor, "_save_correction_noncritical"
        ), mock.patch.object(self.processor, "_sync_legal_cards") as sync:
            self.processor.run_once()
        update.assert_called_once()
        sync.assert_called_once()

        waiting = {F_流转_当前状态: "待法务复核"}
        retry_payload = self._payload(
            review_intent="initial",
            expected_review_version=review_version(waiting),
            submitted_at_ms=1700000000200,
        )
        target = {**waiting, **build_update_fields(retry_payload, waiting)}
        queued = self.store.enqueue_job(
            "legal_review", "rec-retry", "legal-review:retry", retry_payload
        )
        claimed = self.store.claim_job("interrupted")
        self.assertEqual(claimed["id"], queued.item_id)
        self.store.fail_job(
            claimed["id"], retryable=True, category="transient_network"
        )
        with mock.patch.object(
            feishu_api, "get_record", return_value={"fields": target}
        ), mock.patch.object(feishu_api, "update_record") as update, mock.patch.object(
            self.processor, "_save_correction_noncritical"
        ), mock.patch.object(self.processor, "_sync_legal_cards") as sync:
            self.processor.run_once()
        update.assert_not_called()
        sync.assert_called_once()
        self.assertEqual(self.store.get_job(queued.item_id)["status"], SUCCEEDED)

    def test_completed_card_escapes_dynamic_markdown(self):
        card = legal_card_sync.build_completed_legal_card(
            "rec-legal",
            {"reviewer_name": "*[法务](bad)", "verdict": "`通过`"},
        )
        rendered = card["elements"][0]["text"]["content"]
        self.assertIn(r"\*\[法务\]\(bad\)", rendered)
        self.assertIn(r"\`通过\`", rendered)

    def test_frontend_carries_opaque_version_and_handles_stale(self):
        source = Path("static/main.js").read_text(encoding="utf-8")
        self.assertIn("expected_review_version: currentRecord.review_version", source)
        self.assertIn('operation_status === "stale"', source)
        self.assertIn("该物料已有最新审核结果，请刷新查看", source)
        self.assertNotIn("版本冲突", source)


class FeishuUpdateContractTests(unittest.TestCase):
    def test_update_card_uses_patch_and_serialized_content(self):
        response = mock.Mock()
        response.status_code = 200
        response.headers = {"X-Request-Id": "request-test"}
        response.json.return_value = {"code": 0, "data": {}}
        with mock.patch.object(
            feishu_api, "get_tenant_access_token", return_value="token-test"
        ), mock.patch.object(
            feishu_api.requests, "patch", return_value=response
        ) as patch:
            result = feishu_api.update_card("message-test", {"header": {}})
        self.assertTrue(patch.call_args.args[0].endswith("/im/v1/messages/message-test"))
        body = patch.call_args.kwargs["json"]
        self.assertEqual(json.loads(body["content"]), {"header": {}})
        self.assertEqual(result["message_id"], "message-test")


if __name__ == "__main__":
    unittest.main()
