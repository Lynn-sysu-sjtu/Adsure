import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app
import feishu_api
import ocr_preprocessor
from card_action_service import CardActionRequest, handle_card_action
from card_templates import build_final_failure_card
from logging_utils import context_fields
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
        predictor_source = (root / "predictor.py").read_text(encoding="utf-8")
        self.assertNotIn("str(e)", app_source)
        self.assertNotIn("str(e)", bot_source)
        self.assertNotIn("alert(", frontend_source)
        self.assertNotIn("result.message", frontend_source)
        self.assertNotIn("debug=True", app_source)
        self.assertNotIn("BITABLE_APP_TOKEN", (root / "worker.py").read_text(encoding="utf-8"))
        self.assertIn("toast.content = ACTION_RETRY", bot_source)
        self.assertNotIn('toast.content = "这次没有处理完成，请稍后再试"', bot_source)
        self.assertNotIn("data.get('msg')", predictor_source)

    def test_new_structured_logs_mask_record_identifiers(self):
        rendered = context_fields(
            record_id="rec-secret",
            idempotency_key="initial-choice:rec-secret:round:1",
            request_id="req-secret",
            job_id=7,
        )
        self.assertIn("record_id=id#", rendered)
        self.assertNotIn("rec-secret", rendered)
        self.assertIn("idempotency_key=id#", rendered)
        self.assertIn("request_id=id#", rendered)
        self.assertNotIn("req-secret", rendered)

    def test_python_sources_do_not_format_raw_record_ids_in_logs(self):
        root = Path(__file__).resolve().parents[1]
        offenders = []
        for source_path in root.glob("*.py"):
            source = source_path.read_text(encoding="utf-8")
            if "record_id=%s" in source or "record_id=%r" in source:
                offenders.append(source_path.name)
        self.assertEqual(offenders, [])

    def test_ocr_logs_do_not_emit_raw_record_identifier(self):
        record_id = "rec-private-ocr"
        fields = {
            ocr_preprocessor.F_物料附件: [
                {"type": "image/png", "name": "test.png", "file_token": "token"}
            ]
        }
        with mock.patch.object(
            ocr_preprocessor,
            "download_attachment",
            side_effect=RuntimeError("EXPECTED_OCR_FAILURE"),
        ), self.assertLogs(ocr_preprocessor.logger, level="INFO") as captured:
            self.assertEqual(
                ocr_preprocessor.extract_text_from_attachments(record_id, fields), ""
            )

        rendered = "\n".join(captured.output)
        self.assertIn("record_id=id#", rendered)
        self.assertNotIn(record_id, rendered)
        self.assertNotIn("EXPECTED_OCR_FAILURE", rendered)

    def test_optional_route_registration_failures_are_isolated(self):
        cases = (
            (
                "_register_timeline_feature",
                "timeline_routes.register_timeline_routes",
                "event=timeline_routes_registration_failed",
            ),
            (
                "_register_ops_feature",
                "ops_routes.register_ops_routes",
                "event=ops_routes_registration_failed",
            ),
            (
                "_register_memory_feature",
                "memory_routes.register_memory_routes",
                "event=memory_routes_registration_failed",
            ),
        )
        for helper_name, target, expected_event in cases:
            if not hasattr(app, helper_name):
                continue
            secret = f"SECRET_{helper_name}"
            with self.subTest(feature=helper_name), mock.patch(
                target, side_effect=RuntimeError(secret)
            ), self.assertLogs(app.logger, level="WARNING") as captured:
                getattr(app, helper_name)()

            rendered = "\n".join(captured.output)
            self.assertIn(expected_event, rendered)
            self.assertNotIn(secret, rendered)

    def test_public_records_api_does_not_echo_internal_failure(self):
        with mock.patch.object(
            feishu_api, "list_all_records", side_effect=RuntimeError("SECRET_STACK_500"),
        ):
            body, status = app.get_records()
        self.assertEqual(status, 503)
        rendered = repr(body)
        self.assertIn("暂时未能加载，请稍后刷新", rendered)
        self.assertNotIn("SECRET_STACK_500", rendered)

    def test_corrections_api_omits_internal_storage_fields(self):
        stored = [{
            "id": "opaque-correction",
            "record_id": "rec-private",
            "idempotency_key": "legal-review:private",
            "industry": "美妆",
            "content_snippet": "展示片段",
            "status": "active",
        }]
        with mock.patch.object(
            app.preference_memory, "list_all", return_value=stored
        ), mock.patch.object(app, "jsonify", side_effect=lambda value: value):
            body = app.list_corrections()

        self.assertEqual(body[0]["id"], "opaque-correction")
        self.assertEqual(body[0]["industry"], "美妆")
        self.assertNotIn("record_id", body[0])
        self.assertNotIn("idempotency_key", body[0])


if __name__ == "__main__":
    unittest.main()
