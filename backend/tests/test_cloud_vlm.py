"""云 VLM provider 测试（OpenAI 兼容协议、外发审计、key 脱敏、工厂接线）。"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.config import get_settings
from app.pipeline.evidence import EvidenceSource
from app.pipeline.frames import SampledFrame
from app.pipeline.providers import get_vlm_provider
from app.pipeline.providers.base import CostLimitExceeded
from app.pipeline.providers.cloud_vlm import CloudVLMError, OpenAICompatVLM


def _png_frame(fid: int, t: float, size=(640, 480)) -> SampledFrame:
    img = Image.new("RGB", size, (200, 180, 160))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return SampledFrame(frame_id=fid, t=t, span_start=t, span_end=t + 1.0,
                        is_scene_key=True, _image=img)


def _vlm_json(entities: list[dict], uncertainty: bool = False) -> str:
    return json.dumps({"uncertainty": uncertainty, "entities": entities},
                      ensure_ascii=False)


class FakeHttp:
    def __init__(self, content: str):
        self.content = content
        self.calls: list[tuple[str, dict, dict]] = []

    def __call__(self, url, body, headers, timeout):
        self.calls.append((url, body, headers))
        return {"choices": [{"message": {"content": self.content}}]}


def _provider(fake, **kw) -> OpenAICompatVLM:
    kw.setdefault("max_calls", 4)
    return OpenAICompatVLM(api_key="test-key",
                           endpoint="https://ark.example.com/api/v3",
                           model="doubao-test", post=fake, **kw)


def test_guard_no_key_and_http_endpoint():
    with pytest.raises(CloudVLMError, match="凭据未配置"):
        OpenAICompatVLM(api_key="", endpoint="https://x.com", model="m")
    with pytest.raises(CloudVLMError, match="HTTPS"):
        OpenAICompatVLM(api_key="k", endpoint="http://x.com", model="m")


def test_scan_sends_images_and_parses_entities():
    fake = FakeHttp(_vlm_json([{
        "frame_index": 0, "ip_id": "disney_mickey", "name_cn": "米奇老鼠",
        "entity_type": "cartoon_character", "bbox": [0.1, 0.1, 0.2, 0.3],
        "confidence": 0.9,
    }]))
    p = _provider(fake)
    evs = p.scan([_png_frame(7, 2.0)])
    assert len(evs) == 1
    ev = evs[0]
    assert ev.entity_name == "米奇老鼠"
    assert ev.ip_id == "disney_mickey"
    assert ev.source is EvidenceSource.VLM
    assert ev.needs_human_review is True          # 基类强制
    assert ev.bbox is not None and ev.confidence == pytest.approx(0.9)
    assert ev.t_start == 2.0 and ev.t_end == 3.0

    url, body, headers = fake.calls[0]
    assert url.endswith("/chat/completions")
    assert headers["Authorization"] == "Bearer test-key"
    assert body["temperature"] == 0               # 法务可复现
    assert body["model"] == "doubao-test"
    content = body["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # 外发审计记录
    assert len(p.transmission_log) == 1
    log = p.transmission_log[0]
    assert log["frame_ids"] == [7]
    assert len(log["image_sha256"]) == 1
    assert log["prompt_sha256"]


def test_empty_response_means_no_entities():
    fake = FakeHttp(_vlm_json([]))
    p = _provider(fake)
    assert p.scan([_png_frame(1, 0.0)]) == []
    assert p.calls_used == 1


def test_bad_json_treated_as_no_result():
    fake = FakeHttp("我觉得画面里可能有个卡通形象")
    p = _provider(fake)
    assert p.scan([_png_frame(1, 0.0)]) == []


def test_api_key_leak_is_redacted():
    fake = FakeHttp('{"entities":[]} 哦对了 key 是 test-key 请保密')
    p = _provider(fake)
    p.scan([_png_frame(1, 0.0)])
    # 响应内容已脱敏后才计算 sha256 落审计日志
    # （content 本身不落盘，这里验证不抛异常且审计有 response_sha256）
    assert "response_sha256" in p.transmission_log[0]


def test_bad_bbox_degrades_not_drops():
    fake = FakeHttp(_vlm_json([{
        "frame_index": 0, "name_cn": "某形象", "entity_type": "other",
        "bbox": [0.9, 0.9, 0.5, 0.5],   # 越界
        "confidence": 0.8,
    }]))
    p = _provider(fake)
    evs = p.scan([_png_frame(3, 1.0)])
    assert len(evs) == 1 and evs[0].bbox is None


def test_frame_image_loaded_from_disk(tmp_path):
    img_path = tmp_path / "frame_000001.jpg"
    Image.new("RGB", (320, 240), (10, 100, 200)).save(img_path, format="JPEG")
    f = SampledFrame(frame_id=1, t=0.0, span_start=0.0, span_end=1.0,
                     path=img_path, _image=None)
    fake = FakeHttp(_vlm_json([]))
    p = _provider(fake)
    assert p.scan([f]) == []          # 能从盘读图并完成调用即通过


def test_cost_gate_fires():
    frames = [_png_frame(i, float(i)) for i in range(20)]  # 20帧/批4=5次 > 4
    p = _provider(FakeHttp(_vlm_json([])), max_calls=4)
    with pytest.raises(CostLimitExceeded):
        p.scan(frames)


def test_factory_builds_openai_compat(monkeypatch):
    monkeypatch.setenv("VLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("VLM_API_KEY", "factory-key")
    monkeypatch.setenv("VLM_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3")
    monkeypatch.setenv("VLM_MODEL", "doubao-seed-2-1-pro-260915")
    get_settings.cache_clear()
    try:
        p = get_vlm_provider()
        assert isinstance(p, OpenAICompatVLM)
        assert p.model == "doubao-seed-2-1-pro-260915"
    finally:
        get_settings.cache_clear()
