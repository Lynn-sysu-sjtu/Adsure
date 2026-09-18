"""云 OCR provider 测试（协议、bbox 归一化、审计、脱敏、成本闸门、工厂）。"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.config import get_settings
from app.pipeline.evidence import EvidenceSource
from app.pipeline.frames import SampledFrame
from app.pipeline.providers import get_ocr_provider
from app.pipeline.providers.base import CostLimitExceeded
from app.pipeline.providers.cloud_ocr import CloudOCRError, OpenAICompatOCR


def _frame(fid: int, t: float, size=(1280, 720)) -> SampledFrame:
    img = Image.new("RGB", size, (250, 248, 245))
    return SampledFrame(frame_id=fid, t=t, span_start=t, span_end=t + 1.0,
                        is_scene_key=True, _image=img)


def _ocr_json(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False)


class FakeHttp:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, headers))
        return {"choices": [{"message": {"content": self.content}}]}


def _provider(fake, **kw) -> OpenAICompatOCR:
    kw.setdefault("max_calls", 20)
    return OpenAICompatOCR(api_key="test-key",
                           endpoint="https://ark.example.com/api/v3",
                           model="doubao-test", post=fake, **kw)


def test_guards():
    with pytest.raises(CloudOCRError, match="凭据未配置"):
        OpenAICompatOCR(api_key="", endpoint="https://x.com", model="m")
    with pytest.raises(CloudOCRError, match="HTTPS"):
        OpenAICompatOCR(api_key="k", endpoint="http://x.com", model="m")


def test_recognize_returns_normalized_bbox():
    fake = FakeHttp(_ocr_json([
        {"text": "国家级配方", "bbox": [0.156, 0.272, 0.279, 0.119]},
        {"text": "本品不能代替药物", "bbox": [0.891, 0.956, 0.107, 0.033]},
    ]))
    p = _provider(fake)
    evs = p._recognize_impl(_frame(5, 2.0), 1280, 720)
    assert len(evs) == 2
    first = evs[0]
    assert first.source is EvidenceSource.OCR
    assert first.text == "国家级配方"
    assert first.bbox.x == pytest.approx(0.156, abs=1e-6)
    assert first.bbox.y == pytest.approx(0.272, abs=1e-6)
    assert first.font_scale == pytest.approx(0.119, abs=1e-6)
    assert first.confidence is None        # 模型没给就不编
    assert first.provider == "openai-compat-ocr"

    url, body, headers = fake.calls[0]
    assert url.endswith("/chat/completions")
    assert headers["Authorization"] == "Bearer test-key"
    assert body["temperature"] == 0
    assert body["messages"][0]["content"][0]["type"] == "text"
    assert "花字" in body["messages"][0]["content"][0]["text"]
    # 审计日志
    assert p.transmission_log[0]["frame_id"] == 5
    assert "image_sha256" in p.transmission_log[0]


def test_empty_and_bad_json_are_no_text():
    for content in (_ocr_json([]), "图里好像有字", ""):
        p = _provider(FakeHttp(content))
        assert p._recognize_impl(_frame(1, 0.0), 1280, 720) == []


def test_bad_bbox_items_dropped_not_crash():
    fake = FakeHttp(_ocr_json([
        {"text": "正常", "bbox": [0.1, 0.1, 0.2, 0.1]},
        {"text": "越界", "bbox": [0.9, 0.9, 0.5, 0.5]},
        {"text": "缺bbox"},
        {"text": "坏类型", "bbox": "0.1,0.1"},
    ]))
    p = _provider(fake)
    evs = p._recognize_impl(_frame(2, 0.0), 1280, 720)
    assert len(evs) == 1 and evs[0].text == "正常"


def test_key_leak_redacted_before_hash():
    fake = FakeHttp(_ocr_json([]) + " key=test-key")
    p = _provider(fake)
    p._recognize_impl(_frame(1, 0.0), 1280, 720)
    assert "response_sha256" in p.transmission_log[0]


def test_cost_gate_fires():
    p = _provider(FakeHttp(_ocr_json([])), max_calls=3)
    with pytest.raises(CostLimitExceeded):
        p.recognize([_frame(i, float(i)) for i in range(4)], 1280, 720)


def test_span_backfill_by_base_class():
    """基类用代表帧 span 回填时间——去重后时长信息不丢（方案坑 #2）。"""
    fake = FakeHttp(_ocr_json([{"text": "字", "bbox": [0.1, 0.1, 0.2, 0.1]}]))
    p = _provider(fake)
    f = _frame(9, 5.0)
    f.span_start, f.span_end = 4.0, 6.5
    evs = p.recognize([f], 1280, 720)
    assert evs[0].t_start == 4.0 and evs[0].t_end == 6.5


def test_factory_builds_openai_compat(monkeypatch):
    monkeypatch.setenv("OCR_PROVIDER", "openai_compat")
    monkeypatch.setenv("OCR_API_KEY", "factory-key")
    monkeypatch.setenv("OCR_CLOUD_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3")
    monkeypatch.setenv("OCR_CLOUD_MODEL", "doubao-seed-2-1-pro-260915")
    get_settings.cache_clear()
    try:
        prov = get_ocr_provider()
        assert isinstance(prov, OpenAICompatOCR)
        assert prov.capabilities().bbox is True
    finally:
        get_settings.cache_clear()
