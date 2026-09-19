"""Cross-boundary checks for the merged Claude handoff modules.

The handoff remains an optional engine under ``backend/app``.  These tests
prove that it consumes the repository's current case catalog and video-v3
evidence contract instead of relying on the handoff package's old ``refs``
layout.
"""

from __future__ import annotations

import json

from app.crawler.extract import ExtractionResult, to_case
from app.pipeline.interop import load_job
from app.reasoning.cases import CaseLibrary


def test_case_library_reads_current_repository_data():
    library = CaseLibrary.load()
    case = library.by_id("samr_2025_typical_ads_01")
    assert case is not None
    assert case.source_url.startswith("https://www.samr.gov.cn/")
    assert case.verified is True


def test_current_video_v3_job_loads_without_refs_layout(tmp_path):
    job = tmp_path / "job-current-v3"
    job.mkdir()
    (job / "evidence.json").write_text(json.dumps({
        "schema_version": "video-mvp-evidence/v1",
        "job_id": "job-current-v3",
        "items": [{
            "id": "audio_000000",
            "source": "asr",
            "kind": "text",
            "text": "国家级",
            "t_start": 1.0,
            "t_end": 1.6,
            "bbox": None,
            "frame_ids": [],
            "confidence": 0.8,
            "provider": "faster-whisper",
            "provider_version": "medium",
            "raw_ref": {"path": "asr_raw.json", "words": [
                {"word": "国", "start": 1.0, "end": 1.2, "probability": 0.8},
                {"word": "家", "start": 1.2, "end": 1.4, "probability": 0.8},
                {"word": "级", "start": 1.4, "end": 1.6, "probability": 0.8},
            ]},
        }],
    }, ensure_ascii=False), encoding="utf-8")
    (job / "manifest.json").write_text(json.dumps({
        "job_id": "job-current-v3",
        "source": {"file_name": "sample.mp4", "duration_seconds": 3.0},
        "extraction": {"frame_count": 0},
    }), encoding="utf-8")

    bundle = load_job(job)
    assert bundle.review_id == "job-current-v3"
    assert bundle.evidences[0].resolve_time(1, 3) == (1.2, 1.6)


def test_crawler_candidate_emits_root_contract_without_inventing_values():
    case = to_case(
        ExtractionResult(fields={"party_name": "某公司"}),
        "samr_test",
        "https://www.samr.gov.cn/example.html",
        "data/raw_text/samr_test.json",
        "国家市场监督管理总局",
    )
    required = {
        "case_id", "title", "source_name", "source_url", "publish_date",
        "penalty_authority", "party_name", "industry", "product_or_service",
        "ad_channel", "risk_dimensions", "illegal_claims", "facts_summary",
        "legal_basis", "penalty_result", "penalty_amount", "regulatory_logic",
        "mapped_rule_ids", "keywords", "vector_text", "review_status",
        "raw_text_path",
    }
    assert required <= case.keys()
    assert case["review_status"] == "pending_review"
    assert case["approved_for_rag"] is False
    assert case["human_review_required"] is True
    assert case["legal_basis"] == []
    assert case["penalty_amount"] is None
