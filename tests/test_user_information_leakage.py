import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import feishu_api
from card_action_service import CardActionRequest, handle_card_action
from card_templates import build_final_failure_card
from reliable_queue import SQLiteQueue
import user_messages


class UserInformationLeakageTests(unittest.TestCase):
    def test_public_error_messages_and_failure_card_have_no_internal_details(self):
        mock_error = "SECRET_EXCEPTION timeout code=500 open_id=ou-secret token=abc"
        public_values = [
            value for name, value in vars(user_messages).items()
            if name.isupper() and isinstance(value, str)
        ]
        public_values.append(repr(build_final_failure_card("rec-1")))
        rendered = "\n".join(public_values)
        for forbidden in (
            mock_error, "SECRET_EXCEPTION", "Traceback", "open_id", "token=", "timeout",
            "HTTP 500", "code=500", "LLM", "OCR", "API",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_unknown_action_does_not_echo_action_or_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteQueue(str(Path(directory) / "leak.sqlite3"))
            result = handle_card_action(CardActionRequest(
                action="SECRET_EXCEPTION_timeout_500", record_id="rec-1", event_id="evt-1",
            ), store=store)
        self.assertNotIn("SECRET", result.message)
        self.assertNotIn("timeout", result.message)
        self.assertNotIn("500", result.message)

    def test_sources_do_not_concatenate_exceptions_into_public_ui(self):
        root = Path(__file__).resolve().parents[1]
        app_source = (root / "app.py").read_text(encoding="utf-8")
        frontend_source = (root / "static" / "main.js").read_text(encoding="utf-8")
        bot_source = (root / "bot_listener.py").read_text(encoding="utf-8")
        self.assertNotIn("str(e)", app_source)
        self.assertNotIn("str(e)", bot_source)
        self.assertNotIn("alert(", frontend_source)
        self.assertNotIn("result.message", frontend_source)
        self.assertNotIn("debug=True", app_source)
        self.assertNotIn("BITABLE_APP_TOKEN", (root / "worker.py").read_text(encoding="utf-8"))
        self.assertIn("toast.content = ACTION_RETRY", bot_source)
        self.assertNotIn('toast.content = "这次没有处理完成，请稍后再试"', bot_source)

    def test_public_records_api_does_not_echo_internal_failure(self):
        with mock.patch.object(
            feishu_api, "list_all_records", side_effect=RuntimeError("SECRET_STACK_500"),
        ):
            body, status = app.get_records()
        self.assertEqual(status, 503)
        rendered = repr(body)
        self.assertIn("暂时未能加载，请稍后刷新", rendered)
        self.assertNotIn("SECRET_STACK_500", rendered)


if __name__ == "__main__":
    unittest.main()
