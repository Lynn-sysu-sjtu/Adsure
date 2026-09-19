"""火山引擎 豆包录音文件识别大模型版 适配器（试点）。

协议依据火山引擎语音技术公开文档《录音文件识别大模型版》
（https://docs.volcengine.com/docs/6561/2606791，openspeech.bytedance.com，
提交-轮询两段式）。官方示例使用单个 ``x-api-key`` 请求头和公网可下载音频 URL。
在拿到企业凭据完成真实联调之前，本模块统一标记
``live_validation_status = "not_live_validated"``；任何字段名差异以真实响应修正。

隐私边界：仅上传单音轨转码后的 16 kHz 单声道 WAV（base64，在请求体内），
不上传完整视频、画面、证明材料或活动/落地页文本。凭据只从本机私密文件读取。
"""
from __future__ import annotations

import base64
import io
import json
import os
import time
import uuid
import wave
from pathlib import Path
from .env_config import load_env

ROOT = Path(__file__).resolve().parents[2]

NAMES = {
    "VIDEO_MVP_VOLC_SPEECH_API_KEY",
    "VIDEO_MVP_VOLC_SPEECH_APP_KEY",
    "VIDEO_MVP_VOLC_SPEECH_ACCESS_KEY",
    "VIDEO_MVP_VOLC_SPEECH_RESOURCE_ID",
    "VIDEO_MVP_VOLC_SPEECH_BASE_URL",
    "VIDEO_MVP_VOLC_SPEECH_MODEL",
    "VIDEO_MVP_VOLC_HOTWORDS",
    "VIDEO_MVP_VOLC_SPEECH_API_PATH",
    "VIDEO_MVP_VOLC_SPEECH_INLINE_DATA",
    "VIDEO_MVP_VOLC_SPEECH_UID",
}
DEFAULT_BASE_URL = "https://openspeech.bytedance.com"
DEFAULT_RESOURCE_ID = "volc.seedasr.auc"
DEFAULT_MODEL = "bigmodel"
DEFAULT_API_PATH = "/api/v3/auc/bigmodel"
# 火山协议约定 1000 为成功；1001 为识别进行中。其余按失败处理并脱敏记录。
CODE_OK = 1000
CODE_PROCESSING = 1001
HOTWORD_PATH = ROOT / "data" / "rules" / "asr_hotwords.json"


def _values() -> dict[str, str]:
    return load_env(NAMES)


def volc_readiness() -> dict:
    data = _values()
    api_key = _api_key(data)
    base_url = data.get("VIDEO_MVP_VOLC_SPEECH_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    api_path = data.get("VIDEO_MVP_VOLC_SPEECH_API_PATH", DEFAULT_API_PATH)
    resource_id = data.get("VIDEO_MVP_VOLC_SPEECH_RESOURCE_ID", DEFAULT_RESOURCE_ID)
    model_name = data.get("VIDEO_MVP_VOLC_SPEECH_MODEL", DEFAULT_MODEL)
    validated_shape = (
        base_url == DEFAULT_BASE_URL and api_path == DEFAULT_API_PATH
        and resource_id == DEFAULT_RESOURCE_ID and model_name == DEFAULT_MODEL
    )
    return {
        "provider": "volcengine/seed-asr-bigmodel",
        "base_url": base_url,
        "api_path": api_path,
        "resource_id": resource_id,
        "model": model_name,
        "configured": bool(api_key),
        "auth": "x-api-key",
        "audio_submission": "inline_data_validated_20260917",
        "live_validation_status": "live_validated_20260917" if validated_shape else "configuration_changed_not_validated",
    }


def _api_key(data: dict[str, str]) -> str:
    # 当前官方协议只需要 x-api-key；保留旧实验变量名仅为配置兼容。
    return (data.get("VIDEO_MVP_VOLC_SPEECH_API_KEY")
            or data.get("VIDEO_MVP_VOLC_SPEECH_ACCESS_KEY")
            or data.get("VIDEO_MVP_VOLC_SPEECH_APP_KEY")
            or "")


def _hotwords(industry: str) -> list[str]:
    # 官方示例没有 hotwords 字段；默认不发送，待火山确认请求字段后再显式开启。
    if _values().get("VIDEO_MVP_VOLC_HOTWORDS", "0") != "1":
        return []
    try:
        payload = json.loads(HOTWORD_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    words = payload.get("industries", {}).get(industry) or []
    return words[: int(payload.get("max_words_per_industry", 64))]


def _headers(data: dict[str, str], request_id: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-api-key": _api_key(data),
        "X-Api-Resource-Id": data.get("VIDEO_MVP_VOLC_SPEECH_RESOURCE_ID", DEFAULT_RESOURCE_ID),
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
    }


def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    import httpx
    with httpx.Client(trust_env=False, timeout=timeout, follow_redirects=False) as client:
        response = client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return response.json()


def _wav_base64(samples, sample_rate: int = 16000) -> str:
    import numpy as np
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _seconds(value, divisor: float = 1000.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number / divisor


def _field(item: dict, ms_names: tuple[str, ...], second_names: tuple[str, ...], default=0):
    """火山协议毫秒字段优先；仅有秒级字段时按秒读取。"""
    for name in ms_names:
        if name in item:
            return _seconds(item[name], 1000.0)
    for name in second_names:
        if name in item:
            return _seconds(item[name], 1.0)
    return float(default or 0)


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


def _parse_segments(result: dict, track: int, offset: float) -> list[dict]:
    segments: list[dict] = []
    utterances = _utterances(result)
    if utterances:
        for item in utterances:
            text = (item.get("text") or item.get("utterance") or "").strip()
            if not text:
                continue
            start = _field(item, ("start_time", "start_ms"), ("start", "start_s")) + offset
            end = _field(item, ("end_time", "end_ms"), ("end", "end_s"), start) + offset
            words = []
            for word in item.get("words", []) or []:
                token = (word.get("text") or word.get("word") or "").strip()
                if not token:
                    continue
                words.append({"word": token,
                              "start": _field(word, ("start_time", "start_ms"), ("start", "start_s")) + offset,
                              "end": _field(word, ("end_time", "end_ms"), ("end", "end_s")) + offset,
                              "probability": word.get("confidence")})
            segments.append({"text": text, "audio_track": track, "start": start, "end": max(end, start + .1),
                             "confidence": item.get("confidence"), "words": words})
    else:
        text = (result.get("text") or "").strip()
        if text:
            segments.append({"text": text, "audio_track": track, "start": offset, "end": offset,
                             "confidence": None, "words": []})
    return segments


def _submit(job_url: str, data: dict[str, str], audio: dict, hotwords: list[str]) -> str:
    request_id = str(uuid.uuid4())
    body = {
        "user": {"uid": data.get("VIDEO_MVP_VOLC_SPEECH_UID", "adsure-mvp")},
        "audio": audio,
        "request": {
            "model_name": data.get("VIDEO_MVP_VOLC_SPEECH_MODEL", DEFAULT_MODEL),
            "enable_itn": True,
            "enable_punc": True,
            "show_utterances": True,
            "enable_ddc": False,
            "enable_speaker_info": False,
            "enable_channel_split": False,
            "vad_segment": False,
        },
    }
    if hotwords:
        body["request"]["hotwords"] = hotwords
    payload = _post_json(job_url + "/submit", body, _headers(data, request_id), timeout=30.0)
    submit_code = _resp_code(payload)
    if submit_code not in (CODE_OK, None):
        raise RuntimeError(f"volc_asr_submit_rejected:{submit_code}")
    request_id = ((payload.get("added") or {}).get("request_id")
                  or (payload.get("resp") or {}).get("request_id") or request_id)
    if not request_id:
        raise RuntimeError("volc_asr_submit_no_request_id")
    return request_id


def _query(job_url: str, data: dict[str, str], request_id: str) -> dict:
    # 实测 bigmodel query 通过 X-Api-Request-Id 定位任务；请求体带 user 会返回 400。
    body = {}
    payload = _post_json(job_url + "/query", body, _headers(data, request_id), timeout=30.0)
    code = _resp_code(payload)
    if code == CODE_PROCESSING:
        return {"done": False, "result": {}}
    if code not in (CODE_OK, None):
        raise RuntimeError(f"volc_asr_query_failed:{code}")
    result = _result_object(payload)
    # HTTP 200 空壳或只有 audio_info 的响应表示任务仍在处理，不能当作 no_speech。
    if not result.get("text") and not _utterances(result):
        return {"done": False, "result": {}}
    return {"done": True, "result": result}


def _tracks(video: Path) -> list[dict]:
    import av
    with av.open(str(video)) as container:
        return [{"index": stream.index,
                 "offset": float(stream.start_time * stream.time_base) if stream.start_time else 0.0}
                for stream in container.streams if stream.type == "audio"]


def transcribe_worker(video: Path, industry: str = "一般行业") -> dict:
    """提交并轮询单个视频的全部音轨，输出与本地 ASR 相同的报告结构。"""
    data = _values()
    ready = volc_readiness()
    base_url = data.get("VIDEO_MVP_VOLC_SPEECH_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    api_path = data.get("VIDEO_MVP_VOLC_SPEECH_API_PATH", DEFAULT_API_PATH)
    job_url = base_url + api_path
    payload = {
        "status": "no_audio_track", "provider": ready["provider"], "model": ready["model"],
        "model_provenance": {"endpoint": base_url, "resource_id": ready["resource_id"],
                             "api_path": ready["api_path"], "model": ready["model"],
                             "live_validation_status": ready["live_validation_status"]},
        "hotword_industry": industry,
        "audio_tracks": 0, "segments": [], "track_results": [],
        "low_confidence_segments": [], "quality_status": "machine_transcribed_unverified",
    }
    if not ready["configured"]:
        payload["status"] = "failed"
        payload["error"] = "火山语音凭据未配置（VIDEO_MVP_VOLC_SPEECH_API_KEY）"
        return payload

    import tempfile
    import av
    import numpy as np
    from faster_whisper.audio import decode_audio

    tracks = _tracks(video)
    payload["audio_tracks"] = len(tracks)
    if not tracks:
        return payload

    timeout_s = float(os.getenv("VIDEO_MVP_VOLC_POLL_TIMEOUT_S", "180"))
    interval_s = float(os.getenv("VIDEO_MVP_VOLC_POLL_INTERVAL_S", "2"))
    deadline = time.monotonic() + timeout_s
    hotwords = _hotwords(industry)
    inline_allowed = data.get("VIDEO_MVP_VOLC_SPEECH_INLINE_DATA", "0") == "1"
    with tempfile.TemporaryDirectory(prefix="adsure-volc-asr-") as temporary:
        for info in tracks:
            try:
                audio_path = Path(temporary) / f"track-{info['index']}.mka"
                with av.open(str(video)) as source, av.open(str(audio_path), "w", format="matroska") as target:
                    stream = source.streams[info["index"]]
                    out = target.add_stream_from_template(stream)
                    for packet in source.demux(stream):
                        if packet.dts is None:
                            continue
                        packet.stream = out
                        target.mux(packet)
                samples = decode_audio(str(audio_path), sampling_rate=16000)
                duration = len(samples) / 16000
                if not len(samples):
                    raise RuntimeError("音轨为空")
                if float(np.max(np.abs(samples))) < 1e-5:
                    payload["track_results"].append({"track": info["index"], "status": "silent", "duration": duration})
                    continue
                audio = {"format": "wav", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1}
                if inline_allowed:
                    # 官方示例为公网 audio.url；data 字段是否支持必须真实联调确认。
                    audio["data"] = _wav_base64(samples)
                else:
                    raise RuntimeError(
                        "volc_asr_audio_public_url_required：官方示例要求公网可下载 audio.url；"
                        "需先上传至对象存储并生成临时 URL，或显式开启 INLINE_DATA 后验证 data 字段"
                    )
                request_id = _submit(job_url, data, audio, hotwords)
                result: dict = {}
                while True:
                    outcome = _query(job_url, data, request_id)
                    if outcome["done"]:
                        result = outcome["result"]
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("volc_asr_poll_timeout")
                    time.sleep(interval_s)
                segments = _parse_segments(result, info["index"], info["offset"])
                payload["segments"].extend(segments)
                payload["track_results"].append(
                    {"track": info["index"], "status": "transcribed" if segments else "no_speech_detected",
                     "duration": duration, "request_id": request_id})
            except Exception as exc:
                # 仅记录异常类型与协议码，避免响应体/请求头中的凭据进入留痕。
                payload["track_results"].append({"track": info["index"], "status": "failed",
                                                  "error": f"{type(exc).__name__}:{str(exc)[:120]}"})
    states = {item["status"] for item in payload["track_results"]}
    payload["status"] = ("partial" if payload["segments"] else "failed") if "failed" in states else (
        "transcribed" if payload["segments"] else "silent" if states == {"silent"} else "no_speech_detected")
    payload["low_confidence_segments"] = [
        {"start": s["start"], "end": s["end"], "confidence": s.get("confidence")}
        for s in payload["segments"] if s.get("confidence") is None or s["confidence"] < .6
    ]
    if payload["status"] == "failed":
        payload["quality_status"] = "verification_failed"
    return payload
