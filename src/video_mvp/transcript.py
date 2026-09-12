from __future__ import annotations

import json
import math
import re
from pathlib import Path

from .models import EvidenceUnit


TIMESTAMP = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[,.](\d{3})")
TIME_RANGE = re.compile(
    r"(?:(?:\d{1,2}):)?\d{1,2}:\d{2}[,.]\d{3}\s*-->\s*"
    r"(?:(?:\d{1,2}):)?\d{1,2}:\d{2}[,.]\d{3}"
)


def parse_timestamp(value: str) -> float:
    match = TIMESTAMP.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid timestamp: {value}")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    milliseconds = int(match.group(4))
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def _parse_caption_text(text: str) -> list[tuple[float, float, str]]:
    lines = text.replace("\r\n", "\n").split("\n")
    segments: list[tuple[float, float, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not TIME_RANGE.match(line):
            index += 1
            continue
        start_raw, end_raw = [part.strip().split(" ")[0] for part in line.split("-->")]
        index += 1
        caption: list[str] = []
        while index < len(lines) and lines[index].strip():
            caption.append(lines[index].strip())
            index += 1
        content = " ".join(caption).strip()
        if content:
            segments.append((parse_timestamp(start_raw), parse_timestamp(end_raw), content))
    return segments


def _parse_json(path: Path) -> list[tuple[float, float, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("segments") or payload.get("transcript") or []
        if isinstance(payload, dict):
            payload = payload.get("sentences") or []
    if not isinstance(payload, list):
        raise ValueError("transcript JSON must contain a segment list")
    segments = []
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        start = item.get("start", item.get("start_time", item.get("start_ms", 0)))
        end = item.get("end", item.get("end_time", item.get("end_ms", start)))
        if "start_ms" in item:
            start = float(start) / 1000
        if "end_ms" in item:
            end = float(end) / 1000
        segments.append((float(start), float(end), item["text"].strip()))
    return [segment for segment in segments if segment[2]]


def transcript_evidence(
    *,
    transcript_path: Path | None,
    transcript_text: str,
    duration: float,
) -> tuple[list[EvidenceUnit], list[str]]:
    warnings: list[str] = []
    segments: list[tuple[float, float, str]] = []
    provider = "manual transcript"
    if transcript_path is not None:
        suffix = transcript_path.suffix.lower()
        if suffix in {".srt", ".vtt"}:
            segments = _parse_caption_text(transcript_path.read_text(encoding="utf-8-sig"))
            provider = "uploaded timed captions"
        elif suffix == ".json":
            segments = _parse_json(transcript_path)
            provider = "uploaded ASR JSON"
        else:
            transcript_text = transcript_path.read_text(encoding="utf-8-sig")

    if not segments and transcript_text.strip():
        segments = [(0.0, duration, transcript_text.strip())]
        warnings.append("人工文本未提供字级或句级时间戳，口播风险只能定位到完整视频区间。")
    if not segments:
        warnings.append("未提供字幕或 ASR 结果；本次仅审核画面 OCR，不能视为已审核口播。")

    evidence = [
        EvidenceUnit(
            id=f"asr_{index:05d}",
            source="asr",
            kind="text",
            text=text,
            t_start=min(duration, max(0.0, start)),
            t_end=min(duration, max(start, end)),
            provider=provider,
            provider_version="user-supplied",
            raw_ref={"segment_index": index},
        )
        for index, (start, end, text) in enumerate(segments)
        if math.isfinite(start) and math.isfinite(end) and 0 <= start < end and start < duration
    ]
    if len(evidence) != len(segments):
        warnings.append("已丢弃时间戳无效或超出视频时长的字幕段，请检查字幕与视频是否对应。")
    return evidence, warnings
