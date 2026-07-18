# -*- coding: utf-8 -*-
"""Zhipu embedding client for semantic recall.

The endpoint and model are configurable because provider model names can
change. Defaults follow the OpenAI-compatible Zhipu v4 embedding endpoint.
"""

import json
import os
import urllib.error
import urllib.request


class ZhipuEmbeddingClientError(RuntimeError):
    """Raised when embedding generation fails."""


class ZhipuEmbeddingClient:
    def __init__(self, api_key=None, base_url=None, model=None, timeout=60):
        self.api_key = api_key or os.getenv("ZHIPUAI_API_KEY") or os.getenv("ZHIPU_API_KEY")
        self.base_url = (
            base_url
            or os.getenv("ZHIPU_EMBEDDING_BASE_URL")
            or "https://open.bigmodel.cn/api/paas/v4"
        ).rstrip("/")
        self.model = model or os.getenv("ZHIPU_EMBEDDING_MODEL") or "embedding-3"
        self.timeout = timeout
        if not self.api_key:
            raise ZhipuEmbeddingClientError("Missing ZHIPUAI_API_KEY or ZHIPU_API_KEY.")

    def embed_texts(self, texts):
        payload = {"model": self.model, "input": list(texts)}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = self.base_url if self.base_url.endswith("/embeddings") else f"{self.base_url}/embeddings"
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ZhipuEmbeddingClientError(f"Zhipu embedding HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ZhipuEmbeddingClientError(f"Zhipu embedding request failed: {exc}") from exc

        items = sorted(result.get("data", []), key=lambda item: item.get("index", 0))
        embeddings = [item.get("embedding") for item in items]
        if len(embeddings) != len(texts) or any(not vector for vector in embeddings):
            raise ZhipuEmbeddingClientError("Zhipu embedding response shape is invalid.")
        return embeddings
