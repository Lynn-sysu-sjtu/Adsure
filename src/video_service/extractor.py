"""Convert uploaded videos into the shared evidence protocol."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from src.video_mvp.pipeline import analyze_video
from .schemas import (
    BBox, Coverage, CoverageItem, EvidenceBundle, EvidenceRef, EvidenceUnit,
    ExtractorVersion,
)

SERVICE_VERSION = "video-extractor/0.1.0"


def _normalize_audio_status(audio: dict) -> str:
    """Map pipeline audio status to the production coverage vocabulary."""
    status = str(audio.get("status", "unknown"))
    track_results = audio.get("track_results") or []
    if status in {"no_audio_track"}:
        return "no_audio_track"
    if status in {"failed"} and not track_results:
        return "asr_not_installed"
    if status in {"failed", "partial"}:
        return "asr_failed"
    if status == "silent":
        return "audio_track_silent"
    if status == "disabled":
        return "asr_disabled"
    if status == "transcribed":
        return "transcribed"
    return status or "unknown"


def _normalize_frames_status(visual: dict) -> str:
    status = str(visual.get("status", "unknown"))
    if status == "sampled_complete":
        return "sampled_complete"
    if visual.get("sampling_complete") is False or visual.get("omitted_candidates"):
        return "frame_sampling_incomplete"
    if status in {"incomplete", "not_complete"}:
        return "frame_sampling_incomplete"
    if not visual:
        return "frames_not_executed"
    return status or "unknown"


def _normalize_semantic_status(semantic: dict) -> str:
    status = str(semantic.get("status", "unknown"))
    provider = (semantic.get("provider") or {}).get("provider", "")
    if status in {"analyzed"}:
        return "analyzed"
    if status in {"consent_required"}:
        return "cloud_unauthorized"
    if status in {"not_connected"}:
        if provider in {"ollama"}:
            return "local_vlm_not_ready"
        return "vlm_not_configured"
    if status in {"partial"}:
        return "cloud_call_partial"
    if status in {"failed"} or semantic.get("errors"):
        return "cloud_call_failed"
    if status in {"disabled"}:
        return "vlm_disabled"
    return status or "unknown"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bbox(raw: list[float] | tuple[float, ...] | None):
    if not raw or len(raw) != 4:
        return None
    try:
        return BBox(x=float(raw[0]), y=float(raw[1]), width=float(raw[2]), height=float(raw[3]))
    except (TypeError, ValueError):
        return None


def _confidence(value: Any):
    try:
        if value is None:
            return None
        number = float(value)
        return max(0.0, min(1.0, number))
    except (TypeError, ValueError):
        return None


def _ms(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return max(0, int(round(float(value) * 1000)))
    except (TypeError, ValueError):
        return None


def _source_type(item: dict[str, Any]) -> str:
    source = item.get("source", "")
    kind = item.get("kind", "")
    if source == "asr":
        return "audio_transcript"
    if source == "ocr":
        return "frame_ocr"
    if source in {"semantic", "vlm"} or kind == "visual_observation":
        return "visual_observation"
    if source == "material":
        return "material_text"
    return "system"


def _evidence_id(item: dict[str, Any], index: int) -> str:
    raw_id = str(item.get("id") or f"unit-{index:06d}")
    return "ev_" + hashlib.sha256(raw_id.encode()).hexdigest()[:20]


def to_evidence_bundle(*, record_id: str, request_id: str, material_id: str,
                       video_path: Path, work_dir: Path, report: dict,
                       evidence_payload: dict) -> EvidenceBundle:
    units: list[EvidenceUnit] = []
    for index, item in enumerate(evidence_payload.get("items", [])):
        source_type = _source_type(item)
        frame_ids = item.get("frame_ids") or []
        frame_id = frame_ids[0] if frame_ids else None
        ref_kind = "frame" if frame_id else "audio"
        ref_path = f"frames/{frame_id}.jpg" if frame_id else "asr_raw.json"
        provider = str(item.get("provider") or "unknown")
        units.append(EvidenceUnit(
            evidence_id=_evidence_id(item, index),
            source_type=source_type,
            text=str(item.get("text") or ""),
            start_ms=_ms(item.get("t_start")),
            end_ms=_ms(item.get("t_end")),
            frame_id=frame_id,
            bbox=_bbox(item.get("bbox")),
            confidence=_confidence(item.get("confidence")),
            provider=provider,
            provider_version=str(item.get("provider_version") or ""),
            review_status="pending_human_review",
            ref=EvidenceRef(
                kind=ref_kind,
                path=ref_path,
                sha256=(item.get("raw_ref") or {}).get("frame_sha256"),
                frame_id=frame_id,
            ),
        ))

    # Semantic observations are intentionally separate from OCR/ASR and stay model-labelled.
    for index, observation in enumerate((report.get("visual_semantics") or {}).get("observations", [])):
        text = observation.get("description") or observation.get("text") or ""
        if not text:
            continue
        frame_ids = observation.get("frame_ids") or []
        frame_id = frame_ids[0] if frame_ids else None
        units.append(EvidenceUnit(
            evidence_id="ev_visual_" + hashlib.sha256(
                (str(index) + str(frame_id) + text).encode()).hexdigest()[:20],
            source_type="visual_observation",
            text=text,
            start_ms=_ms(observation.get("t_start")),
            end_ms=_ms(observation.get("t_end")),
            frame_id=frame_id,
            bbox=None,
            confidence=None,
            provider=str((report.get("visual_semantics") or {}).get("provider", {}).get("provider") or "visual-model"),
            provider_version=str((report.get("visual_semantics") or {}).get("provider", {}).get("model") or ""),
            review_status="model_observation_unverified",
            ref=EvidenceRef(kind="frame", path=f"frames/{frame_id}.jpg" if frame_id else "semantic_raw.json",
                            frame_id=frame_id),
        ))

    coverage_raw = report.get("coverage") or {}
    audio = coverage_raw.get("audio") or {"status": "not_executed"}
    visual = coverage_raw.get("visual") or {"status": "not_executed"}
    semantic = report.get("visual_semantics") or {"status": "not_executed"}
    overall = "complete" if report.get("analysis_status") == "completed" else (
        "partial" if units else "not_proven")
    audio_status = _normalize_audio_status(audio)
    frames_status = _normalize_frames_status(visual)
    semantic_status = _normalize_semantic_status(semantic)
    ocr_executed = any(u.source_type == "frame_ocr" for u in units)
    coverage = Coverage(
        overall=overall,
        audio=CoverageItem(status=audio_status, details=audio),
        frames=CoverageItem(status=frames_status, details=visual),
        ocr=CoverageItem(status="executed" if ocr_executed else "ocr_not_executed",
                         details={"engine": visual.get("engine", ""), "sample_count": visual.get("sample_count")}),
        visual_semantics=CoverageItem(status=semantic_status, details=semantic),
        rule_engine=CoverageItem(status="not_called", details={}),
    )
    return EvidenceBundle(
        record_id=record_id,
        request_id=request_id,
        material_id=material_id,
        material_type="video",
        file_sha256=sha256(video_path),
        evidence_units=units,
        coverage=coverage,
        warnings=list(report.get("warnings") or []),
        extractor_version=ExtractorVersion(
            service=SERVICE_VERSION,
            version=report.get("schema_version", "unknown"),
            asr={"status": audio.get("status"), "provider": audio.get("provider"), "verification": audio.get("verification", {}).get("provider")},
            ocr={"engine": visual.get("engine"), "sample_count": visual.get("sample_count")},
            vlm={"status": semantic.get("status"), "provider": (semantic.get("provider") or {}).get("provider"),
                 "model": (semantic.get("provider") or {}).get("model")},
        ),
    )


def extract_video(*, record_id: str, request_id: str, material_id: str,
                  video_path: Path, work_dir: Path, industry: str, platform: str,
                  product_category: str, cloud_consent_endpoint: str = "") -> EvidenceBundle:
    work_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("VIDEO_MVP_OCR_ENGINE", os.getenv("VIDEO_MVP_OCR_ENGINE", "rapidocr"))
    report = analyze_video(
        video_path,
        work_dir,
        job_id=material_id,
        industry=industry,
        product_category=product_category,
        platform=platform,
        sample_interval=float(os.getenv("VIDEO_SERVICE_SAMPLE_INTERVAL", "0.5")),
        max_frames=int(os.getenv("VIDEO_SERVICE_MAX_FRAMES", "1800")),
        asr_mode="auto",
        cloud_consent_endpoint=cloud_consent_endpoint,
    )
    evidence_path = work_dir / "evidence.json"
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    return to_evidence_bundle(record_id=record_id, request_id=request_id, material_id=material_id,
                              video_path=video_path, work_dir=work_dir, report=report,
                              evidence_payload=evidence_payload)


def disk_free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free
