import tempfile
import unittest
from pathlib import Path
from unittest import mock

from card_action_service import CardActionRequest, handle_card_action
from reliable_queue import SQLiteQueue
from user_messages import ACTION_ACCEPTED, ACTION_IN_PROGRESS, STALE_CARD


class CardActionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteQueue(str(Path(self.tmp.name) / "actions.sqlite3"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_http_and_websocket_same_event_create_one_job(self):
        common = dict(
            action="start_ai_review",
            record_id="rec-1",
            operator_id="ou-1",
            event_id="event-shared",
            round=1,
        )
        http = handle_card_action(
            CardActionRequest(**common, transport="http"), store=self.store
        )
        websocket = handle_card_action(
            CardActionRequest(**common, transport="websocket"),
            store=self.store,
        )

        self.assertTrue(http.created)
        self.assertEqual(http.message, ACTION_ACCEPTED)
        self.assertFalse(websocket.created)
        self.assertEqual(websocket.message, ACTION_IN_PROGRESS)
        self.assertEqual(len(self.store.list_jobs()), 1)

    def test_skip_and_escalate_enqueue_the_shared_legal_job_type(self):
        for action in ("skip_review", "escalate_to_legal"):
            with self.subTest(action=action):
                result = handle_card_action(
                    CardActionRequest(
                        action=action,
                        record_id=f"rec-{action}",
                        event_id=f"evt-{action}",
                        round=1,
                    ),
                    store=self.store,
                )
                self.assertEqual(result.message, ACTION_ACCEPTED)
                job = self.store.get_job(result.job_id)
                self.assertEqual(job["job_type"], "route_to_legal")
                self.assertEqual(job["payload"]["source"], action)

    def test_valid_legacy_confirm_mode_is_supported(self):
        with mock.patch(
            "card_action_service._legacy_record_status",
            return_value="运营起草",
        ) as state_read:
            result = handle_card_action(
                CardActionRequest(
                    action="confirm_mode",
                    mode="深度",
                    record_id="rec-1",
                    event_id="evt-mode",
                ),
                store=self.store,
            )
        self.assertTrue(result.created)
        state_read.assert_called_once_with("rec-1")
        self.assertEqual(self.store.get_job(result.job_id)["payload"]["mode"], "深度")

    def test_unknown_or_invalid_legacy_action_is_stale_without_details(self):
        unknown = handle_card_action(
            CardActionRequest(
                action="unknown",
                record_id="rec-1",
                event_id="evt-unknown",
            ),
            store=self.store,
        )
        invalid_mode = handle_card_action(
            CardActionRequest(
                action="confirm_mode",
                mode="内部模式",
                record_id="rec-1",
                event_id="evt-mode",
            ),
            store=self.store,
        )
        self.assertEqual(unknown.message, STALE_CARD)
        self.assertEqual(invalid_mode.message, STALE_CARD)
        self.assertEqual(len(self.store.list_jobs()), 0)

    def test_resubmit_duplicate_clicks_share_one_job_and_next_round_is_allowed(self):
        first = handle_card_action(
            CardActionRequest(
                action="resubmit",
                record_id="rec-1",
                event_id="evt-1",
                round=1,
            ),
            store=self.store,
        )
        duplicate = handle_card_action(
            CardActionRequest(
                action="resubmit",
                record_id="rec-1",
                event_id="evt-1",
                round=1,
            ),
            store=self.store,
        )
        second = handle_card_action(
            CardActionRequest(
                action="resubmit",
                record_id="rec-1",
                event_id="evt-2",
                round=1,
            ),
            store=self.store,
        )
        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertFalse(second.created)
        claimed = self.store.claim_job("worker")
        self.store.advance_round_once("rec-1", claimed["idempotency_key"])
        self.store.complete_job(claimed["id"])
        next_round = handle_card_action(
            CardActionRequest(
                action="resubmit",
                record_id="rec-1",
                event_id="evt-3",
                round=2,
            ),
            store=self.store,
        )
        self.assertTrue(next_round.created)
        self.assertEqual(len(self.store.list_jobs()), 2)

    def test_start_then_skip_creates_only_one_initial_choice(self):
        start = handle_card_action(
            CardActionRequest(
                action="start_ai_review",
                record_id="rec-start-first",
                event_id="evt-start",
                round=1,
            ),
            store=self.store,
        )
        skip = handle_card_action(
            CardActionRequest(
                action="skip_review",
                record_id="rec-start-first",
                event_id="evt-skip",
                round=1,
            ),
            store=self.store,
        )

        self.assertTrue(start.created)
        self.assertFalse(skip.created)
        self.assertEqual(skip.message, ACTION_IN_PROGRESS)
        jobs = self.store.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_type"], "context_confirm")
        self.assertEqual(
            jobs[0]["idempotency_key"], "initial-choice:rec-start-first:round:1"
        )

    def test_skip_then_start_creates_only_one_initial_choice(self):
        skip = handle_card_action(
            CardActionRequest(
                action="skip_review",
                record_id="rec-skip-first",
                event_id="evt-skip",
                round=1,
            ),
            store=self.store,
        )
        start = handle_card_action(
            CardActionRequest(
                action="start_ai_review",
                record_id="rec-skip-first",
                event_id="evt-start",
                round=1,
            ),
            store=self.store,
        )

        self.assertTrue(skip.created)
        self.assertEqual(skip.message, ACTION_ACCEPTED)
        self.assertFalse(start.created)
        self.assertEqual(start.message, ACTION_IN_PROGRESS)
        jobs = self.store.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_type"], "route_to_legal")
        self.assertEqual(
            jobs[0]["idempotency_key"], "initial-choice:rec-skip-first:round:1"
        )

    def test_unversioned_action_with_wrong_source_status_is_stale(self):
        with mock.patch(
            "card_action_service._legacy_record_status",
            return_value="待法务复核",
        ) as state_read:
            result = handle_card_action(
                CardActionRequest(
                    action="skip_review",
                    record_id="rec-old",
                    event_id="evt-old",
                ),
                store=self.store,
            )

        self.assertEqual(result.message, STALE_CARD)
        self.assertFalse(result.created)
        self.assertEqual(self.store.list_jobs(), [])
        state_read.assert_called_once_with("rec-old")

    def test_escalate_key_does_not_block_later_resubmit(self):
        escalated = handle_card_action(
            CardActionRequest(
                action="escalate_to_legal",
                record_id="rec-followup",
                event_id="evt-escalate",
                round=1,
            ),
            store=self.store,
        )
        resubmitted = handle_card_action(
            CardActionRequest(
                action="resubmit",
                record_id="rec-followup",
                event_id="evt-resubmit",
                round=1,
            ),
            store=self.store,
        )

        self.assertTrue(escalated.created)
        self.assertTrue(resubmitted.created)
        keys = {job["idempotency_key"] for job in self.store.list_jobs()}
        self.assertEqual(
            keys,
            {
                "legal-route:rec-followup:round:1",
                "resubmit:rec-followup:round:1",
            },
        )


if __name__ == "__main__":
    unittest.main()
