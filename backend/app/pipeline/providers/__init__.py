"""Provider 工厂。

换供应商的唯一开关在 .env 的 ASR_PROVIDER / OCR_PROVIDER / VLM_PROVIDER，
业务代码只跟抽象基类打交道，永远不 import 具体实现。
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.pipeline.providers.base import (
    ASRCapabilities,
    ASRProvider,
    CapabilityError,
    CostLimitExceeded,
    OCRCapabilities,
    OCRProvider,
    ProviderError,
    VLMProvider,
    font_scale_from_bbox,
    to_normalized_bbox,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ASRCapabilities",
    "ASRProvider",
    "CapabilityError",
    "CostLimitExceeded",
    "OCRCapabilities",
    "OCRProvider",
    "ProviderError",
    "VLMProvider",
    "font_scale_from_bbox",
    "to_normalized_bbox",
    "get_asr_provider",
    "get_ocr_provider",
    "get_vlm_provider",
]


def get_asr_provider(name: str | None = None) -> ASRProvider:
    settings = get_settings()
    name = name or settings.asr_provider

    if name == "mock":
        from app.pipeline.providers.mock import MockASRProvider

        return MockASRProvider()

    if name == "volcengine":
        from app.pipeline.providers.volcengine import VolcSeedASR

        return VolcSeedASR(
            api_key=settings.asr_volc_api_key.get_secret_value(),
            resource_id=settings.asr_volc_resource_id,
            base_url=settings.asr_volc_base_url,
            api_path=settings.asr_volc_api_path,
            model=settings.asr_volc_model,
            uid=settings.asr_volc_uid,
        )

    raise NotImplementedError(
        f"ASR provider「{name}」尚未实现。\n"
        "当前可用: mock、volcengine（Seed-ASR，响应强制复验字级时间戳）。"
    )


def get_ocr_provider(name: str | None = None) -> OCRProvider:
    settings = get_settings()
    name = name or settings.ocr_provider
    max_calls = settings.pipeline.max_ocr_calls_per_video

    if name == "mock":
        from app.pipeline.providers.mock import MockOCRProvider

        return MockOCRProvider(max_calls=max_calls)

    raise NotImplementedError(
        f"OCR provider「{name}」尚未实现。当前可用: mock。\n"
        "云实现接入时需确认返回文字框坐标（bbox），"
        "否则 L4 显著性核查无法进行。"
    )


def get_vlm_provider(name: str | None = None) -> VLMProvider:
    settings = get_settings()
    name = name or settings.vlm_provider
    max_calls = settings.pipeline.max_vlm_calls_per_video

    if name == "mock":
        from app.pipeline.providers.mock import MockVLMProvider

        return MockVLMProvider(max_calls=max_calls)

    if name == "openai_compat":
        from app.pipeline.providers.cloud_vlm import OpenAICompatVLM

        return OpenAICompatVLM(
            api_key=settings.vlm_api_key.get_secret_value(),
            endpoint=settings.vlm_endpoint,
            model=settings.vlm_model,
            max_calls=max_calls,
            batch_size=settings.pipeline.vlm_batch_size
            if hasattr(settings.pipeline, "vlm_batch_size") else 4,
        )

    raise NotImplementedError(
        f"VLM provider「{name}」尚未实现。当前可用: mock、openai_compat。"
    )
