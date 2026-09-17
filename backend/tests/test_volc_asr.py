"""火山 Seed-ASR provider 测试（提交-轮询协议、字级硬校验、工厂接线）。"""

from __future__ import annotations

import io
import uuid
import wave
from pathlib import Path

import pytest

from app.config import get_settings
from app.pipeline.providers import get_asr_provider
from app.pipeline.providers.base import CapabilityError
from app.pipeline.providers.volcengine import (
    CODE_PROCESSING,
    DEFAULT_MODEL,
    DEFAULT_RESOURCE_ID,
    VolcSeedASR,
    WordTimestampMissing,
    parse_seed_asr_result,
)


# ── 构造件 ───────────────────────────────────────────────────


def _word(ch: str, start_ms: int, dur_ms: int = 100) -> dict:
    return {"text": ch, "start_time": start_ms,
            "end_time": start_ms + dur_ms, "confidence": 0}


def _utterance(text: str, words: list[dict], start_ms: int = 0,
               end_ms: int | None = None) -> dict:
    if end_ms is None:
        end_ms = words[-1]["end_time"] if words else 0
    return {"text": text, "start_time": start_ms, "end_time": end_ms,
            "confidence": None, "words": words}


def _words_for(text: str, t0_ms: int, step: int = 100) -> list[dict]:
    out, t = [], t0_ms
    for ch in text:
        out.append(_word(ch, t, step))
        t += step
    return out


def _done_payload(utterances: list[dict]) -> dict:
    return {"added": {"result": {"utterances": utterances}}}


@pytest.fixture
def wav_file(tmp_path: Path) -> Path:
    p = tmp_path / "track.wav"
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)  # 1 秒静音
    p.write_bytes(buf.getvalue())
    return p


class FakeHttp:
    """按 /submit、/query 返回脚本化响应，并记录全部请求供断言。"""

    def __init__(self, query_responses: list[dict],
                 submit_response: dict | None = None):
        rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "test-rid"))
        self.submit_response = submit_response or {"resp": {"code": 1000, "request_id": rid}}
        self.query_responses = list(query_responses)
        self.calls: list[tuple[str, dict, dict]] = []
        self._qi = 0

    def __call__(self, url, body, headers, timeout):
        if url.endswith("/submit"):
            self.calls.append(("submit", body, headers))
            return self.submit_response
        self.calls.append(("query", body, headers))
        r = self.query_responses[min(self._qi, len(self.query_responses) - 1)]
        self._qi += 1
        return r


# ── 解析层：字级硬校验（方案 §6/§14③，不满足就换供应商）──────


def test_parse_ok_with_punctuation_dropped_and_millisecond_units():
    words = _words_for("本品是国家级配方", 5600)
    result = {"utterances": [_utterance("本品是国家级配方。", words)]}
    evs = parse_seed_asr_result(result)
    assert len(evs) == 1
    ev = evs[0]
    assert ev.text == "本品是国家级配方"          # 标点不进 text（游标对齐约定）
    assert ev.t_start == pytest.approx(5.6)
    assert ev.t_end == pytest.approx(6.4)
    assert len(ev.word_timings) == 8
    # 关键承诺：命中「国家级」时 resolve_time 必须取到 国/家/级 三字的时间
    t0, t1 = ev.resolve_time(3, 6)
    assert (t0, t1) == (pytest.approx(5.9), pytest.approx(6.2))
    assert ev.provider == "volcengine/seed-asr-bigmodel"
    assert ev.confidence is None                  # 供应商没给置信度就不许编


def test_parse_segment_level_only_is_rejected():
    with pytest.raises(WordTimestampMissing):
        parse_seed_asr_result({"text": "只有段级文本，没有字级时间"})


def test_parse_utterance_without_words_is_rejected():
    with pytest.raises(WordTimestampMissing):
        parse_seed_asr_result({"utterances": [_utterance("有句子没字", [])]})


def test_parse_low_coverage_is_rejected():
    utt = _utterance("ABCDEFGHIJKLMNOPQRST", _words_for("AB", 0))
    with pytest.raises(WordTimestampMissing, match="覆盖率"):
        parse_seed_asr_result({"utterances": [utt]})


def test_parse_non_monotonic_is_rejected():
    words = _words_for("甲乙丙", 1000)
    words[2]["start_time"] = 500                   # 时间回退
    with pytest.raises(WordTimestampMissing, match="单调"):
        parse_seed_asr_result({"utterances": [_utterance("甲乙丙", words, 0, 2000)]})


def test_parse_empty_result_means_no_speech():
    assert parse_seed_asr_result({}) == []
    assert parse_seed_asr_result({"text": "  "}) == []


def test_parse_second_unit_fields_also_accepted():
    utt = {"text": "你好", "start": 1.0, "end": 1.4,
           "words": [{"word": "你", "start": 1.0, "end": 1.2},
                     {"word": "好", "start": 1.2, "end": 1.4}]}
    evs = parse_seed_asr_result({"utterances": [utt]})
    assert evs[0].t_start == 1.0 and evs[0].t_end == 1.4


# ── 提交-轮询链路（不触网，用 FakeHttp）──────────────────────


def _provider(fake: FakeHttp, **kw) -> VolcSeedASR:
    return VolcSeedASR(api_key="test-key", post=fake, sleep=lambda _s: None, **kw)


def test_submit_poll_happy_path(wav_file):
    words = _words_for("国家级配方", 3200)
    fake = FakeHttp([{"resp": {"code": CODE_PROCESSING}},
                     _done_payload([_utterance("国家级配方，", words)])])
    evs = _provider(fake).transcribe(wav_file)
    assert len(evs) == 1 and evs[0].text == "国家级配方"
    assert evs[0].raw_ref["resource_id"] == DEFAULT_RESOURCE_ID

    submit_body, submit_headers = fake.calls[0][1], fake.calls[0][2]
    assert submit_headers["x-api-key"] == "test-key"
    assert submit_headers["X-Api-Resource-Id"] == DEFAULT_RESOURCE_ID
    req = submit_body["request"]
    assert req["show_utterances"] is True        # 字级字段的请求前提
    assert req["model_name"] == DEFAULT_MODEL
    assert submit_body["audio"]["data"]           # base64 wav
    # query 请求体必须为空（实测带 user 返回 400）
    assert fake.calls[1][1] == {}
    assert fake.calls[1][2]["X-Api-Request-Id"]


def test_submit_rejected_raises(wav_file):
    fake = FakeHttp([], submit_response={"resp": {"code": 2000, "message": "bad"}})
    with pytest.raises(CapabilityError, match="submit_rejected:2000"):
        _provider(fake).transcribe(wav_file)


def test_query_failure_raises(wav_file):
    fake = FakeHttp([{"resp": {"code": 2001}}])
    with pytest.raises(CapabilityError, match="query_failed:2001"):
        _provider(fake).transcribe(wav_file)


def test_poll_timeout_raises(wav_file):
    fake = FakeHttp([{"resp": {"code": CODE_PROCESSING}}])
    with pytest.raises(TimeoutError, match="poll_timeout"):
        _provider(fake, poll_timeout_seconds=0).transcribe(wav_file)


def test_missing_key_raises(wav_file):
    with pytest.raises(CapabilityError, match="凭据未配置"):
        VolcSeedASR(api_key="").transcribe(wav_file)


def test_non_wav_rejected(tmp_path):
    p = tmp_path / "audio.txt"
    p.write_text("not a wav")
    with pytest.raises(CapabilityError, match="WAV"):
        _provider(FakeHttp([])).transcribe(p)


def test_runtime_segment_level_response_is_rejected(wav_file):
    # 链路通了但供应商悄悄改成段级输出：仍必须硬失败
    fake = FakeHttp([{"added": {"result": {"text": "整段文本无words"}}}])
    with pytest.raises(WordTimestampMissing):
        _provider(fake).transcribe(wav_file)


def test_empty_shell_is_pending_then_done(wav_file):
    words = _words_for("你好", 0)
    fake = FakeHttp([
        {"added": {"result": {"audio_info": {}}}},      # 空壳=处理中
        _done_payload([_utterance("你好", words)]),
    ])
    evs = _provider(fake).transcribe(wav_file)
    assert len(evs) == 1 and evs[0].text == "你好"


# ── 工厂接线 ─────────────────────────────────────────────────


def test_factory_builds_volcengine(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "volcengine")
    monkeypatch.setenv("ASR_VOLC_API_KEY", "factory-key")
    get_settings.cache_clear()
    try:
        p = get_asr_provider()
        assert isinstance(p, VolcSeedASR)
        assert p.capabilities().word_timestamps is True
        assert p.resource_id == DEFAULT_RESOURCE_ID
    finally:
        get_settings.cache_clear()


# ── 验收脚本（scripts/verify_asr_word_timestamps.py）─────────


def _load_verify_script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_asr_word_timestamps.py"
    import sys

    spec = importlib.util.spec_from_file_location("verify_asr_word_timestamps", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_asr_word_timestamps"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_acceptance_verify_detects_segment_level(tmp_path):
    mod = _load_verify_script()
    good = tmp_path / "good.json"
    good.write_text(
        '{"provider":"volcengine/seed-asr-bigmodel","status":"transcribed",'
        '"segments":[{"text":"国家级","start":3.2,"end":3.8,'
        '"words":[{"word":"国","start":3.2,"end":3.4},'
        '{"word":"家","start":3.4,"end":3.6},{"word":"级","start":3.6,"end":3.8}]}]}',
        encoding="utf-8")
    ok, _ = mod.verify_file(good)
    assert ok

    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"provider":"x","status":"transcribed",'
        '"segments":[{"text":"只有段级","start":0,"end":2,"words":[]}]}',
        encoding="utf-8")
    ok, lines = mod.verify_file(bad)
    assert not ok and any("段级" in l for l in lines)


def test_acceptance_measure_against_labels(tmp_path):
    mod = _load_verify_script()
    asr = tmp_path / "asr.json"
    asr.write_text(
        '{"segments":[{"text":"国家级配方",'
        '"words":[{"word":"国","start":3.30,"end":3.45},'
        '{"word":"家","start":3.45,"end":3.60},{"word":"级","start":3.60,"end":3.75},'
        '{"word":"配","start":3.75,"end":3.9},{"word":"方","start":3.9,"end":4.0}]}]}',
        encoding="utf-8")
    labels = tmp_path / "labels.yaml"
    labels.write_text(
        "cases:\n"
        "  - phrase: 国家级\n    true_start: 3.20\n    true_end: 3.75\n",
        encoding="utf-8")
    ok, lines = mod.measure_file(asr, labels, tolerance=0.5)
    assert ok and any("起点误差 0.10" in l for l in lines)

    # 超出 0.5s 容忍必须 FAIL
    labels.write_text(
        "cases:\n  - phrase: 国家级\n    true_start: 2.00\n", encoding="utf-8")
    ok2, _ = mod.measure_file(asr, labels, tolerance=0.5)
    assert not ok2
