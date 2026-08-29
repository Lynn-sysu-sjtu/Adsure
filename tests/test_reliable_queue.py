import tempfile
import unittest
from pathlib import Path

from reliable_queue import (
    RETRYABLE_FAILED,
    RUNNING,
    SUCCEEDED,
    SQLiteQueue,
)


class ReliableQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteQueue(
            str(Path(self.tmp.name) / "queue.sqlite3"),
            lease_seconds=10,
            retry_base_seconds=0.01,
            retry_max_seconds=0.01,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_job_idempotency_and_single_active_review(self):
        first = self.store.enqueue_job("ai_review", "rec-1", "event-1")
        duplicate = self.store.enqueue_job("ai_review", "rec-1", "event-1")
        active = self.store.enqueue_job("ai_review", "rec-1", "event-2")

        self.assertTrue(first.created)
        self.assertFalse(duplicate.created)
        self.assertEqual(duplicate.item_id, first.item_id)
        self.assertFalse(active.created)
        self.assertEqual(active.reason, "active_review")

        claimed = self.store.claim_job("worker-a", now=100)
        self.assertIsNone(claimed)  # The job was scheduled using the real current time.
        claimed = self.store.claim_job("worker-a")
        self.assertEqual(claimed["status"], RUNNING)
        self.store.complete_job(claimed["id"], {"ok": True})
        self.assertEqual(self.store.get_job(first.item_id)["status"], SUCCEEDED)

        next_round = self.store.enqueue_job("ai_review", "rec-1", "event-2")
        self.assertTrue(next_round.created)

    def test_expired_running_job_is_recovered(self):
        item = self.store.enqueue_job("resubmit", "rec-1", "event-1", run_at=10)
        claimed = self.store.claim_job("worker-a", now=10)
        self.assertEqual(claimed["id"], item.item_id)
        self.assertEqual(claimed["status"], RUNNING)

        recovered = self.store.claim_job("worker-b", now=21)
        self.assertEqual(recovered["id"], item.item_id)
        self.assertEqual(recovered["attempts"], 2)

    def test_failed_recipient_retries_without_touching_successful_recipient(self):
        one = self.store.enqueue_delivery(
            job_id=None, business_action="legal", record_id="rec-1",
            recipient_id="ou-1", card_type="legal_review",
            idempotency_key="legal:rec-1:ou-1", run_at=10,
        )
        two = self.store.enqueue_delivery(
            job_id=None, business_action="legal", record_id="rec-1",
            recipient_id="ou-2", card_type="legal_review",
            idempotency_key="legal:rec-1:ou-2", run_at=10,
        )

        first = self.store.claim_delivery("worker", now=10)
        self.store.complete_delivery(first["id"], "message-1")
        second = self.store.claim_delivery("worker", now=10)
        self.assertEqual(second["id"], two.item_id)
        status = self.store.fail_delivery(second["id"], retryable=True, category="transient_network")
        self.assertEqual(status, RETRYABLE_FAILED)

        rows = {row["id"]: row for row in self.store.list_deliveries()}
        self.assertEqual(rows[one.item_id]["status"], SUCCEEDED)
        self.assertEqual(rows[two.item_id]["status"], RETRYABLE_FAILED)


if __name__ == "__main__":
    unittest.main()
