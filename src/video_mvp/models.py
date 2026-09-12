from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EvidenceUnit:
    id: str
    source: str
    kind: str
    text: str
    t_start: float
    t_end: float
    bbox: list[float] | None = None
    frame_ids: list[str] = field(default_factory=list)
    confidence: float | None = None
    provider: str = ""
    provider_version: str = ""
    raw_ref: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskCandidate:
    risk_id: str
    title: str
    severity: str
    disposition: str
    review_status: str
    risk_dimension: str
    matched_text: str
    t_start: float
    t_end: float
    bbox: list[float] | None
    evidence_ids: list[str]
    rule_ids: list[str]
    legal_basis: list[dict]
    explanation: str
    recommendation: str
    automated_finding: str
    context_text: str = ""
    match_method: str = "normalized_pattern"
    source: str = ""
    pattern_id: str = ""
    occurrences: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RequirementCheck:
    check_id: str
    title: str
    status: str
    coverage_ratio: float | None
    evidence_ids: list[str]
    rule_ids: list[str]
    explanation: str
    review_status: str = "pending_human_review"

    def to_dict(self) -> dict:
        return asdict(self)
