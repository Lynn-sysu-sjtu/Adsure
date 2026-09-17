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

    raise NotImplementedError(
        f"ASR provider「{name}」尚未实现。\n"
        "当前可用: mock（无需 API key，用于链路联调与测试）。\n"
        "云实现待开通账号后补齐 —— 接入时**第一件事**是验证返回字段里\n"
        "确实带 word-level timestamp，不满足就换供应商，不要将就。"
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

    raise NotImplementedError(
        f"VLM provider「{name}」尚未实现。当前可用: mock。"
    )
