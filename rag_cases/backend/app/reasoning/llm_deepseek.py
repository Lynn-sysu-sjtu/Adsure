"""DeepSeek LLM Provider。

与取证层的 Provider 抽象同构：换供应商只改 .env 的 LLM_PROVIDER，
业务代码不动。

⚠️ 本层依赖**结构化 JSON 回包** —— 涵摄推理靠解析要件答案，
   抽取靠解析字段与引用。自由文本会让两边都失败，
   所以强制开启 JSON 输出模式，并把「只输出 JSON」写进系统提示。
"""

from __future__ import annotations

import logging

from app.reasoning.subsume import LLMProvider

logger = logging.getLogger(__name__)


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: float = 120.0,
        temperature: float = 0.0,
        max_retries: int = 2,
    ):
        if not api_key:
            raise ValueError(
                "DeepSeek 未配置 API key。请在 .env 里设置 "
                "LEX_DEEPSEEK_API_KEY（或 LLM_API_KEY）。"
            )
        self.api_key = api_key
        self.base_url = (base_url or "https://api.deepseek.com").rstrip("/")
        self.model = model or "deepseek-chat"
        self.timeout = timeout
        # 法律判断要可复现：同一份素材两次审核给出不同结论，
        # 法务没法用，也没法追责。所以温度固定为 0。
        self.temperature = temperature
        self.max_retries = max_retries
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def complete(self, system: str, user: str) -> str:
        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                r = httpx.post(
                    f"{self.base_url}/chat/completions",
                    json=payload, headers=headers, timeout=self.timeout,
                )
                if r.status_code == 429 or r.status_code >= 500:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                data = r.json()

                usage = data.get("usage") or {}
                self.calls += 1
                self.prompt_tokens += usage.get("prompt_tokens", 0)
                self.completion_tokens += usage.get("completion_tokens", 0)

                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    wait = 2 ** attempt
                    logger.warning("DeepSeek 调用失败（第 %d 次），%ds 后重试：%s",
                                   attempt + 1, wait, exc)
                    import time
                    time.sleep(wait)

        raise RuntimeError(f"DeepSeek 调用失败（已重试 {self.max_retries} 次）：{last_exc}")

    def usage_summary(self) -> str:
        return (f"DeepSeek 调用 {self.calls} 次 · "
                f"输入 {self.prompt_tokens} token · 输出 {self.completion_tokens} token")
