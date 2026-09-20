import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import audit_service
import timeline_routes
from reliable_queue import SQLiteQueue


class AuditTimelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteQueue(os.path.join(self.tmp.name, "audit.sqlite3"))
        self.enabled = mock.patch(
            "audit_service.audit_timeline_enabled", return_value=True
        )
        self.enabled.start()

    def tearDown(self):
        self.enabled.stop()
        self.tmp.cleanup()

    def test_public_events_keep_order_and_hide_internal_fields(self):
        event_types = [
            ("material_submitted", {"round": 1}),
            ("legal_cards_sync_scheduled", {"count": 2}),
            ("delivery_replayed", {"count": 1}),
            (
                "legal_review_completed",
                {
                    "round": 3,
                    "reviewer_name": "法务甲",
                    "verdict": "通过",
                    "is_edit": False,
                    "secret": "DO_NOT_RETURN",
                },
            ),
        ]
        for index, (event_type, summary) in enumerate(event_types):
            audit_service.record_event(
                event_type,
                record_id="rec-1",
                event_key=f"event:{index}",
                summary=summary,
                job_id=99,
                delivery_id=88,
                store=self.store,
                internal=event_type in audit_service.INTERNAL_EVENT_TYPES,
            )
        events = audit_service.public_timeline("rec-1", store=self.store)
        serialized = json.dumps(events, ensure_ascii=False)
        self.assertEqual(
            [item["title"] for item in events],
            [
                "物料已提交",
                "法务审核已完成",
            ],
        )
        for forbidden in (
            "legal_cards_sync_scheduled",
            "delivery_replayed",
            "event_key",
            "job_id",
            "delivery_id",
            "summary",
            "DO_NOT_RETURN",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_retry_is_deduplicated_and_disabled_mode_writes_nothing(self):
        first = audit_service.record_event(
            "ai_review_completed",
            record_id="rec-1",
            event_key="ai-complete:job:1",
            summary={"round": 1, "risk_level": "中"},
            store=self.store,
        )
        duplicate = audit_service.record_event(
            "ai_review_completed",
            record_id="rec-1",
            event_key="ai-complete:job:1",
            summary={"round": 1, "risk_level": "高"},
            store=self.store,
        )
        with mock.patch("audit_service.audit_timeline_enabled", return_value=False):
            disabled = audit_service.record_event(
                "material_resubmitted",
                record_id="rec-1",
                event_key="disabled",
                store=self.store,
            )
        self.assertTrue(first)
        self.assertFalse(duplicate)
        self.assertFalse(disabled)
        self.assertEqual(len(self.store.list_audit_events("rec-1")), 1)

    def test_audit_failure_does_not_escape_business_boundary(self):
        broken = mock.Mock()
        broken.append_audit_event.side_effect = RuntimeError("SECRET_DATABASE")
        result = audit_service.record_event(
            "material_submitted",
            record_id="rec-1",
            event_key="broken",
            store=broken,
        )
        self.assertFalse(result)

    def test_route_is_404_when_disabled_and_failure_is_generic(self):
        with mock.patch(
            "timeline_routes.audit_timeline_enabled", return_value=False
        ), mock.patch("timeline_routes.public_timeline") as timeline:
            response = timeline_routes.get_record_timeline("rec-1")
        self.assertEqual(response, ("", 404))
        timeline.assert_not_called()

        with mock.patch(
            "timeline_routes.audit_timeline_enabled", return_value=True
        ), mock.patch(
            "timeline_routes.public_timeline",
            side_effect=RuntimeError("SECRET_TIMELINE"),
        ), mock.patch(
            "timeline_routes._jsonify", side_effect=lambda payload: payload
        ):
            response = timeline_routes.get_record_timeline("rec-1")
        payload, status = response
        self.assertEqual(status, 503)
        self.assertEqual(payload["message"], "暂未显示")
        self.assertNotIn("record_id", payload)
        self.assertNotIn("SECRET_TIMELINE", json.dumps(payload, ensure_ascii=False))

    def test_frontend_uses_safe_dom_and_stale_response_guard(self):
        source = Path("static/timeline.js").read_text(encoding="utf-8")
        self.assertIn("textContent", source)
        self.assertIn("requestNumber !== latestRequest", source)
        self.assertIn("暂无时间线记录", source)
        self.assertIn("暂未显示", source)
        self.assertNotIn("innerHTML", source)


if __name__ == "__main__":
    unittest.main()
