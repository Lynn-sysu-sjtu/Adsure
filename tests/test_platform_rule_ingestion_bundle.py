import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/platform_rules/manifest_2026-09-04.json"
CANDIDATE_PATH = (
    PROJECT_ROOT
    / "data/platform_rules/structured_candidates/2026-09-04/beauty_platform_rule_candidates.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_platform_rule_source_manifest_preserves_downloaded_provenance():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["catalog_status"] == "candidate_only_not_for_production"
    assert manifest["source_count"] == len(manifest["sources"]) == 12

    for source in manifest["sources"]:
        assert source["review_status"] == "pending_human_review"
        assert source["effective_status"] == "pending_effective_review"
        assert source["manual_verification_url"].startswith("https://")
        assert source["final_http_status"] == 200
        raw_path = PROJECT_ROOT / source["raw_path"]
        text_path = PROJECT_ROOT / source["raw_text_path"]
        assert raw_path.is_file()
        assert text_path.is_file()
        assert _sha256(raw_path) == source["raw_sha256"]


def test_platform_rule_candidates_remain_outside_production_catalog():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    catalog = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    source_ids = {source["source_id"] for source in manifest["sources"]}

    assert catalog["catalog_status"] == "candidate_only_not_for_production"
    assert catalog["candidate_count"] == len(catalog["rules"]) == 31
    for rule in catalog["rules"]:
        assert rule["source_id"] in source_ids
        assert rule["review_status"] == "pending_legal_review"
        assert rule["effective_status"] == "pending_effective_review"
        assert rule["release_eligibility"] == "candidate_only"
        assert rule["human_review_required"] is True
        assert len(rule["retrieval_text"]) >= 30
