from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.semantic_index import (
    build_index,
    configured_encoder,
    zhipu_encoder,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raises=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._raises = raises

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")

    def json(self):
        return self._payload


def vec(value: float, dim: int = 4) -> list[float]:
    return [value, 0.0, 0.0, 0.0][:dim] if dim == 4 else [value] * dim


class ZhipuEncoderTests(unittest.TestCase):
    def test_batches_dimensions_and_normalization(self):
        calls = []

        def fake_post(url, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            batch = json["input"]
            return FakeResponse(payload={
                "model": json["model"],
                "data": [
                    {"index": i, "embedding": [3.0, 4.0, 0.0, 0.0]}
                    for i in range(len(batch))
                ],
            })

        client = MagicMock()
        client.return_value.__enter__.return_value.post.side_effect = fake_post
        with patch("httpx.Client", client):
            encode = zhipu_encoder(api_key="k", model="embedding-3", dimensions=4,
                                   batch_size=2)
            rows = encode(["a", "b", "c"])
        self.assertEqual(2, len(calls))
        self.assertEqual(["a", "b"], calls[0]["json"]["input"])
        self.assertEqual(["c"], calls[1]["json"]["input"])
        self.assertEqual(4, calls[0]["json"]["dimensions"])
        self.assertEqual("Bearer k", calls[0]["headers"]["Authorization"])
        # L2 normalized: (3,4,0,0) -> (0.6,0.8,0,0)
        for row in rows:
            self.assertAlmostEqual(0.6, row[0], places=5)
            self.assertAlmostEqual(0.8, row[1], places=5)

    def test_missing_api_key_raises(self):
        with self.assertRaises(ValueError):
            zhipu_encoder(api_key="")

    def test_http_error_propagates(self):
        client = MagicMock()
        client.return_value.__enter__.return_value.post.return_value = FakeResponse(status_code=401)
        with patch("httpx.Client", client):
            encode = zhipu_encoder(api_key="k")
            with self.assertRaises(RuntimeError):
                encode(["x"])

    def test_configured_encoder_selects_zhipu(self):
        env = {
            "CASE_ENGINE_EMBEDDING_PROVIDER": "zhipu",
            "CASE_ENGINE_EMBEDDING_MODEL": "embedding-3",
            "CASE_ENGINE_ZHIPU_EMBEDDING_MODEL": "embedding-3",
            "CASE_ENGINE_EMBEDDING_DIMENSIONS": "4",
            "ZHIPU_API_KEY": "k",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch("src.semantic_index.zhipu_encoder", return_value=lambda t: [[1.0] * 4 for _ in t]) as z:
            encode = configured_encoder("embedding-3", local_files_only=True)
            self.assertEqual([[1.0] * 4], encode(["x"]))
            self.assertEqual("k", z.call_args.kwargs["api_key"])

    def test_build_index_with_injected_encoder(self):
        chunks = [
            {"chunk_id": "c1", "case_id": "case1", "text": "虚假宣传",
             "search_fields": {"vector_text": "虚假宣传"}},
            {"chunk_id": "c2", "case_id": "case2", "text": "绝对化用语",
             "search_fields": {"vector_text": "绝对化用语"}},
        ]
        index = build_index(chunks, model_name="embedding-3",
                            encoder=lambda t: [[1.0, 0.0] for _ in t])
        self.assertEqual(2, index["document_count"])
        self.assertEqual(2, index["dimension"])
        self.assertEqual("embedding-3", index["model_name"])


if __name__ == "__main__":
    unittest.main()
