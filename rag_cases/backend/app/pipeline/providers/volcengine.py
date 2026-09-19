# -*- coding: utf-8 -*-
"""火山引擎 · 豆包录音文件识别大模型版（Seed-ASR bigmodel）Provider。

协议依据火山引擎语音技术公开文档《录音文件识别大模型版》
（https://docs.volcengine.com/docs/6561/2606791，openspeech.bytedance.com，
提交-轮询两段式）。2026-09-17 已在旧 MVP（src/video_mvp/volc_asr.py）
用 16.44s 美妆视频音轨完成一次真实联调，本文件把同一协议移植到取证层
Provider 抽象后面。

数据外发边界（与旧 MVP 一致）：
  - 只发 16 kHz 单声道 WAV（base64，在请求体内），不发视频/画面/材料；
  - 凭据只从环境变量读，代码与日志不落密钥，异常只记异常类型与协议码。

⚠️ 字级时间戳是硬指标（实施方案 §6/§14 事项③）：
  本 provider 声明 word_timestamps=True，且在**每次响应**上强制校验
  words 字段真的存在且覆盖文本；一旦供应商改成只给段级时间，
  直接抛 WordTimestampMissing 拒绝出报告 —— 不静默降级，立刻换供应商。
"""

from __future__ import annotations

import base64
import logging
import time
import uuid
from pathlib import Path
from typing import Callable

from app.pipeline.evidence import (
    EvidenceSource,
    TextEvidence,
    WordTiming,
)
from app.pipeline.providers.base import (
    ASRCapabilities,
    ASRProvider,
    CapabilityError,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openspeech.bytedance.com"
DEFAULT_API_PATH = "/api/v3/auc/bigmodel"
DEFAULT_RESOURCE_ID = "volc.seedasr.auc"
DEFAULT_MODEL = "bigmodel"

# 火山协议约定 1000 为成功；1001 为识别进行中。
CODE_OK = 1000
CODE_PROCESSING = 1001

# 字级覆盖校验阈值：word token 拼出的字数 / 文本去标点字数。
# 低于这个值说明 words 与 text 不对齐（可能是伪字级），拒绝使用。
WORD_COVERAGE_MIN = 0.9

# 单字 token 异常跨度告警（不抛错；中文正常 0.1–0.6s）
SLOW_WORD_WARN_SECONDS = 2.0

PostFn = Callable[[str, dict, dict, float], dict]


class WordTimestampMissing(CapabilityError):
    """供应商实际响应不满足字级时间戳硬指标。

    与初始化期的能力闸门互补：声明的能力不算数，真实返回的字段才算数。
    """


# ──────────────────────────────────────────────────────────────
#  纯解析层（不触网，供离线验收脚本与测试复用）
# ──────────────────────────────────────────────────────────────


def _seconds(value, divisor: float = 1000.0) -> float | None:
    try:
        return float(value) / divisor
    except (TypeError, ValueError):
        return None


def _field(item: dict, ms_names: tuple[str, ...],
           second_names: tuple[str, ...], default: float = 0.0) -> float:
    """毫秒字段优先；仅有秒级字段时按秒读取。"""
    for name in ms_names:
        if name in item:
            v = _seconds(item[name], 1000.0)
            if v is not None:
                return v
    for name in second_names:
        if name in item:
            v = _seconds(item[name], 1.0)
            if v is not None:
                return v
    return default


def _resp_code(payload: dict):
    resp = payload.get("resp") or payload.get("response") or {}
    header = payload.get("header") or {}
    return resp.get("code", payload.get("code", header.get("code")))


def _result_object(payload: dict) -> dict:
    added = payload.get("added") or {}
    for key in ("result", "recognition_result"):
        if isinstance(added.get(key), dict):
            return added[key]
    resp = payload.get("resp") or {}
    if isinstance(resp.get("result"), dict):
        nested = resp["result"].get("result")
        return nested if isinstance(nested, dict) else resp["result"]
    if isinstance(payload.get("result"), dict):
        nested = payload["result"].get("result")
        return nested if isinstance(nested, dict) else payload["result"]
    return {}


def _utterances(result: dict) -> list[dict]:
    for key in ("utterances", "utterances_list", "sentences"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []


_PUNCT = "，。！？；：、,.!?;:「」『』“”‘’\"'（）()【】[]《》<>…—-· \t\n\r"


def _strip_punct(s: str) -> str:
    return "".join(ch for ch in s if ch not in _PUNCT)


def parse_seed_asr_result(result: dict) -> list[TextEvidence]:
    """识别结果对象 → TextEvidence 列表。

    text 刻意由 word token 拼接（与 LocalWhisperASR 同一约定）：
    火山的 words 不含标点，若保留带标点的 utterance text，resolve_time 的
    字符游标会在第一个标点后整体错位，时间戳静默偏移。标点不承载违禁词，
    丢掉不影响匹配。
    """
    if not isinstance(result, dict):
        raise WordTimestampMissing("识别结果不是对象，无法校验字级时间戳")

    utterances = _utterances(result)
    evidences: list[TextEvidence] = []

    if utterances:
        for i, item in enumerate(utterances):
            raw_text = (item.get("text") or item.get("utterance") or "").strip()
            if not raw_text:
                continue
            start = _field(item, ("start_time", "start_ms"), ("start", "start_s"))
            end = _field(item, ("end_time", "end_ms"), ("end", "end_s"), start)

            raw_words = item.get("words") or []
            words, parts, prev_end = [], [], None
            for w in raw_words:
                token = (w.get("text") or w.get("word") or "").strip()
                if not token:
                    continue
                ws = _field(w, ("start_time", "start_ms"), ("start", "start_s"))
                we = _field(w, ("end_time", "end_ms"), ("end", "end_s"), ws)
                if prev_end is not None and ws + 0.05 < prev_end:
                    raise WordTimestampMissing(
                        f"字级时间戳非单调（{token}: {ws:.2f} < 上一字 {prev_end:.2f}），拒绝使用"
                    )
                prev_end = we
                words.append(WordTiming(text=token, t_start=ws, t_end=max(we, ws)))
                parts.append(token)
                if we - ws > SLOW_WORD_WARN_SECONDS:
                    logger.warning("字 token「%s」跨度 %.2fs，疑似段级时间伪装成字级", token, we - ws)

            # 硬校验：有文本却没有字级时间 → 供应商不满足合同，立刻报错
            if not words:
                raise WordTimestampMissing(
                    "返回 utterance 不含 words 字级时间戳字段。"
                    "字级时间戳是硬指标，请更换供应商，不要降级到段级时间。"
                )

            text = "".join(parts)
            coverage = len(text) / max(1, len(_strip_punct(raw_text)))
            if coverage < WORD_COVERAGE_MIN:
                raise WordTimestampMissing(
                    f"words 对文本的覆盖率 {coverage:.0%} < {WORD_COVERAGE_MIN:.0%}，"
                    "字级时间戳与文本不对齐，拒绝使用"
                )

            conf = item.get("confidence")
            conf = conf if isinstance(conf, (int, float)) and 0 <= conf <= 1 else None
            evidences.append(TextEvidence(
                id=f"asr-{i:04d}",
                source=EvidenceSource.ASR,
                text=text,
                t_start=words[0].t_start,
                t_end=words[-1].t_end if words[-1].t_end >= start else max(end, start),
                word_timings=words,
                confidence=conf,
                provider="volcengine/seed-asr-bigmodel",
                provider_version=DEFAULT_MODEL,
            ))
        return evidences

    # 没有 utterances：只有整段 text 是段级输出 → 硬失败；
    # 完全没有 text 才是「无人声」的正常空结果。
    if (result.get("text") or "").strip():
        raise WordTimestampMissing(
            "返回只有段级 text、没有 utterances/words 字级时间戳。"
            "字级时间戳是硬指标，请更换供应商，不要将就段级输出。"
        )
    return []


# ──────────────────────────────────────────────────────────────
#  Provider
# ──────────────────────────────────────────────────────────────


class VolcSeedASR(ASRProvider):
    """火山 Seed-ASR 录音文件识别。提交-轮询两段式，x-api-key 认证。"""

    name = "volcengine-seed-asr"

    def __init__(
        self,
        api_key: str,
        resource_id: str = DEFAULT_RESOURCE_ID,
        base_url: str = DEFAULT_BASE_URL,
        api_path: str = DEFAULT_API_PATH,
        model: str = DEFAULT_MODEL,
        uid: str = "adsure",
        poll_timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 2.0,
        post: PostFn | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = api_key
        self.resource_id = resource_id
        self.job_url = base_url.rstrip("/") + api_path
        self.model = model
        self.uid = uid
        self.poll_timeout_seconds = poll_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._post = post or self._http_post
        self._sleep = sleep or time.sleep
        self.last_request_id: str | None = None
        super().__init__()

    def capabilities(self) -> ASRCapabilities:
        # 真实联调（2026-09-17）确认 words 字段带 start/end 字级时间；
        # 每次响应另由 parse_seed_asr_result 强制复验。
        return ASRCapabilities(word_timestamps=True, punctuation=True, hotwords=False)

    @staticmethod
    def _http_post(url: str, body: dict, headers: dict, timeout: float) -> dict:
        import httpx

        with httpx.Client(trust_env=False, timeout=timeout,
                          follow_redirects=False) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()

    def _headers(self, request_id: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }

    def transcribe(self, audio_path: Path,
                   hotwords: list[str] | None = None) -> list[TextEvidence]:
        if not self.api_key:
            # 不在初始化期失败：测试与工厂构造不应依赖凭据；真正调用时必须有。
            raise CapabilityError("火山语音凭据未配置（ASR_VOLC_API_KEY）")

        audio_path = Path(audio_path)
        audio_b64 = self._read_wav_base64(audio_path)
        request_id = self._submit(audio_b64)
        result = self._poll(request_id)
        evidences = parse_seed_asr_result(result)
        for ev in evidences:
            ev.provider_version = f"seed-asr/{self.model}"
            ev.raw_ref = {"request_id": request_id, "resource_id": self.resource_id,
                          "audio_path": str(audio_path)}
        return evidences

    @staticmethod
    def _read_wav_base64(audio_path: Path) -> str:
        data = audio_path.read_bytes()
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise CapabilityError(
                f"{audio_path} 不是 WAV 文件；取证层 extract_audio 应产出 16k 单声道 WAV"
            )
        return base64.b64encode(data).decode("ascii")

    def _submit(self, audio_b64: str) -> str:
        request_id = str(uuid.uuid4())
        body = {
            "user": {"uid": self.uid},
            "audio": {
                "format": "wav", "codec": "raw", "rate": 16000,
                "bits": 16, "channel": 1, "data": audio_b64,
            },
            "request": {
                "model_name": self.model,
                "enable_itn": True,
                "enable_punc": True,
                # 字级时间戳的前提：要 utterances，words 在其中返回
                "show_utterances": True,
                "enable_ddc": False,
                "enable_speaker_info": False,
                "enable_channel_split": False,
                "vad_segment": False,
            },
        }
        payload = self._post(self.job_url + "/submit", body,
                             self._headers(request_id), 30.0)
        code = _resp_code(payload)
        if code not in (CODE_OK, None):
            raise CapabilityError(f"volc_asr_submit_rejected:{code}")
        request_id = ((payload.get("added") or {}).get("request_id")
                      or (payload.get("resp") or {}).get("request_id")
                      or request_id)
        if not request_id:
            raise CapabilityError("volc_asr_submit_no_request_id")
        self.last_request_id = request_id
        return request_id

    def _poll(self, request_id: str) -> dict:
        deadline = time.monotonic() + self.poll_timeout_seconds
        # 实测 bigmodel query 通过 X-Api-Request-Id 定位任务；请求体带 user 会 400。
        while True:
            payload = self._post(self.job_url + "/query", {},
                                 self._headers(request_id), 30.0)
            code = _resp_code(payload)
            if code == CODE_PROCESSING:
                pending = True
            elif code not in (CODE_OK, None):
                raise CapabilityError(f"volc_asr_query_failed:{code}")
            else:
                result = _result_object(payload)
                # HTTP 200 空壳或只有 audio_info 表示仍在处理，不能当 no_speech
                if result.get("text") or _utterances(result):
                    return result
                pending = True

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"volc_asr_poll_timeout（{self.poll_timeout_seconds:.0f}s，"
                    f"request_id={request_id}）"
                )
            self._sleep(self.poll_interval_seconds)
