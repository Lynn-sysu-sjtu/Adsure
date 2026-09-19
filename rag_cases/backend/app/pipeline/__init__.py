"""取证层：把视频压成带时间戳的可审证据流。

对外只暴露 EvidenceBundle —— 找法层不应该知道 ffmpeg、OCR provider 这些细节。
"""

from app.pipeline.evidence import (
    BBox,
    Evidence,
    EvidenceBundle,
    EvidenceSource,
    TextEvidence,
    TranscriptIndex,
    VisualEntityEvidence,
)

__all__ = [
    "BBox",
    "Evidence",
    "EvidenceBundle",
    "EvidenceSource",
    "TextEvidence",
    "TranscriptIndex",
    "VisualEntityEvidence",
]
