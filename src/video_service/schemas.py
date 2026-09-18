"""Shared evidence protocol for the video material parsing service."""
from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

EvidenceSourceType = Literal[
    "audio_transcript", "frame_ocr", "visual_observation", "material_text", "system"
]
JobStatus = Literal["queued", "processing", "completed", "partial", "failed"]
ReviewStatus = Literal[
    "pending_human_review", "machine_candidate", "model_observation_unverified", "not_applicable"
]


class BBox(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)
    coordinate_system: str = "top_left_normalized"


class EvidenceRef(BaseModel):
    kind: str
    path: str
    sha256: Optional[str] = None
    frame_id: Optional[str] = None


class EvidenceUnit(BaseModel):
    evidence_id: str
    source_type: EvidenceSourceType
    text: str
    start_ms: Optional[int] = Field(default=None, ge=0)
    end_ms: Optional[int] = Field(default=None, ge=0)
    frame_id: Optional[str] = None
    bbox: Optional[BBox] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    provider: str
    provider_version: Optional[str] = None
    review_status: ReviewStatus = "pending_human_review"
    ref: EvidenceRef


class CoverageItem(BaseModel):
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class Coverage(BaseModel):
    overall: Literal["complete", "partial", "not_proven", "failed"]
    audio: CoverageItem
    frames: CoverageItem
    ocr: CoverageItem
    visual_semantics: CoverageItem
    rule_engine: CoverageItem


class ExtractorVersion(BaseModel):
    service: str
    version: str
    asr: dict[str, Any] = Field(default_factory=dict)
    ocr: dict[str, Any] = Field(default_factory=dict)
    vlm: dict[str, Any] = Field(default_factory=dict)


class EvidenceBundle(BaseModel):
    record_id: str
    request_id: str
    material_id: str
    material_type: Literal["video"]
    file_sha256: str
    evidence_units: list[EvidenceUnit]
    coverage: Coverage
    warnings: list[str] = Field(default_factory=list)
    extractor_version: ExtractorVersion


class RuleEngineResult(BaseModel):
    status: Literal["completed", "failed", "skipped"]
    request_id: str
    response: Optional[dict[str, Any]] = None
    request_payload: Optional[dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int = 0


class VideoJobResult(BaseModel):
    job_id: str
    record_id: str
    request_id: str
    material_id: str
    status: JobStatus
    evidence: Optional[EvidenceBundle] = None
    rule_engine: RuleEngineResult
    warnings: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: str
    updated_at: str
