# -*- coding: utf-8 -*-
"""Small DeepSeek chat client used by the rule-engine LLM layer."""

import json
import os
import urllib.error
import urllib.request


class DeepSeekClientError(RuntimeError):
    """Raised when the DeepSeek API cannot return a usable response."""


class DeepSeekClient:
    def __init__(self, api_key=None, base_url=None, model=None, timeout=60):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.model = model or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
        self.timeout = timeout
        if not self.api_key:
            raise DeepSeekClientError("Missing DEEPSEEK_API_KEY.")

    def create_chat_completion(self, messages, model=None, temperature=0.1, response_format=None):
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise DeepSeekClientError(f"DeepSeek API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekClientError(f"DeepSeek API request failed: {exc}") from exc
