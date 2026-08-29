import sys
import types
import unittest
from unittest import mock


if "requests" not in sys.modules:
    requests = types.ModuleType("requests")
    requests.post = requests.get = requests.put = lambda *_args, **_kwargs: None
    sys.modules["requests"] = requests
if "config" not in sys.modules:
    config = types.ModuleType("config")
    config.FEISHU_APP_ID = "test-app"
    config.FEISHU_APP_SECRET = "test-secret"
    config.BITABLE_APP_TOKEN = "test-base"
    config.BITABLE_TABLE_ID = "test-table"
    sys.modules["config"] = config

import feishu_api


class _Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.headers = {"X-Request-Id": "request-internal"}

    def json(self):
        return self.payload


class _BrokenResponse(_Response):
    def json(self):
        raise ValueError("malformed gateway response")


class FeishuMessageContractTests(unittest.TestCase):
    def test_card_send_uses_official_uuid_in_request_body(self):
        response = _Response({"code": 0, "data": {"message_id": "message-internal"}})
        with mock.patch.object(feishu_api, "get_tenant_access_token", return_value="token-internal"), \
                mock.patch.object(feishu_api.requests, "post", return_value=response) as post:
            result = feishu_api.send_card(
                "ou-recipient", {"elements": []}, idempotency_uuid="stable-uuid",
            )

        request_body = post.call_args.kwargs["json"]
        self.assertEqual(request_body["uuid"], "stable-uuid")
        self.assertEqual(request_body["receive_id"], "ou-recipient")
        self.assertEqual(result["message_id"], "message-internal")

    def test_rate_limit_is_retryable_but_invalid_recipient_is_permanent(self):
        responses = [
            _Response({"code": 99991400}),
            _Response({"code": 230001}),
        ]
        with mock.patch.object(feishu_api, "get_tenant_access_token", return_value="token-internal"), \
                mock.patch.object(feishu_api.requests, "post", side_effect=responses):
            with self.assertRaises(feishu_api.FeishuAPIError) as limited:
                feishu_api.send_card("ou-recipient", {}, idempotency_uuid="uuid-1")
            with self.assertRaises(feishu_api.FeishuAPIError) as invalid:
                feishu_api.send_card("ou-recipient", {}, idempotency_uuid="uuid-2")

        self.assertEqual(limited.exception.category, "rate_limited")
        self.assertTrue(limited.exception.retryable)
        self.assertEqual(invalid.exception.category, "invalid_recipient")
        self.assertFalse(invalid.exception.retryable)

    def test_malformed_server_response_remains_retryable(self):
        with self.assertRaises(feishu_api.FeishuAPIError) as failed:
            feishu_api._response_data(_BrokenResponse({}, status_code=502))
        self.assertEqual(failed.exception.category, "transient_network")
        self.assertTrue(failed.exception.retryable)


if __name__ == "__main__":
    unittest.main()
