import os
import unittest
from unittest.mock import patch

import audit_api


class AuditApiAuthTests(unittest.TestCase):
    def test_rejects_when_server_key_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            result = audit_api.validate_api_key("anything")

        self.assertEqual(-1, result["code"])
        self.assertIn("API Key", result["msg"])
        self.assertIsNone(result["data"])

    def test_rejects_missing_or_wrong_header(self):
        with patch.dict(os.environ, {"ADSURE_API_KEY": "expected"}):
            missing = audit_api.validate_api_key(None)
            wrong = audit_api.validate_api_key("wrong")

        self.assertEqual(-1, missing["code"])
        self.assertEqual(-1, wrong["code"])

    def test_accepts_valid_header(self):
        with patch.dict(os.environ, {"ADSURE_API_KEY": "expected"}):
            result = audit_api.validate_api_key("expected")

        self.assertIsNone(result)

    def test_http_handler_uses_auth_before_audit(self):
        if audit_api.app is None:
            self.skipTest("FastAPI is not installed")
        with patch.dict(os.environ, {"ADSURE_API_KEY": "expected"}):
            with patch.object(audit_api, "audit_endpoint", return_value={"code": 0, "msg": "ok", "data": {}}) as fake_audit:
                rejected = audit_api.post_audit({"record_id": "rec"}, x_api_key="wrong")
                accepted = audit_api.post_audit({"record_id": "rec"}, x_api_key="expected")

        self.assertEqual(-1, rejected["code"])
        self.assertEqual(0, accepted["code"])
        fake_audit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
