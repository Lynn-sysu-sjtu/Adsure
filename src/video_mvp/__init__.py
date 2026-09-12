"""Adsure video-ad review MVP.

The package is intentionally isolated from the penalty-case ingestion pipeline.
It produces auditable evidence and review candidates; it never mutates source
case data and never turns a retrieval result into a legal conclusion.
"""

def analyze_video(*args, **kwargs):
    from .pipeline import analyze_video as analyze
    return analyze(*args, **kwargs)

__all__ = ["analyze_video"]
