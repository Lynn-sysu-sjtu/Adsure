import hashlib
import sys
import time
import types
import unittest

import callback_security


class CallbackSecurityTests(unittest.TestCase):
    def setUp(self):
        self.config = sys.modules.get("config") or types.ModuleType("config")
        sys.modules["config"] = self.config
        self.config.FEISHU_CALLBACK_VERIFY_ENABLED = True
        self.config.FEISHU_VERIFICATION_TOKEN = "verify-token"
        self.config.FEISHU_ENCRYPT_KEY = "encrypt-key"
        self.config.FEISHU_CALLBACK_MAX_AGE_SECONDS = 300

    def test_valid_signature_is_accepted(self):
        timestamp = str(int(time.time()))
        nonce = "nonce"
        raw = b'{"token":"verify-token"}'
        signature = hashlib.sha256(
            timestamp.encode() + nonce.encode() + b"encrypt-key" + raw
        ).hexdigest()
        headers = {
            "X-Lark-Request-Timestamp": timestamp,
            "X-Lark-Request-Nonce": nonce,
            "X-Lark-Signature": signature,
        }
        self.assertTrue(callback_security.verify_http_callback(
            headers, raw, {"token": "verify-token"},
        ))

    def test_old_timestamp_and_bad_signature_are_rejected(self):
        old = str(int(time.time()) - 301)
        headers = {
            "X-Lark-Request-Timestamp": old,
            "X-Lark-Request-Nonce": "nonce",
            "X-Lark-Signature": "bad",
        }
        self.assertFalse(callback_security.verify_http_callback(
            headers, b"{}", {"token": "verify-token"},
        ))

    def test_disabled_verification_keeps_existing_callbacks_compatible(self):
        self.config.FEISHU_CALLBACK_VERIFY_ENABLED = False
        self.assertTrue(callback_security.verify_http_callback({}, b"{}", {}))


if __name__ == "__main__":
    unittest.main()
