"""L3 需资质/需授权词库测试（实施方案 v2：与 IP 命中同走「要材料」路径）。"""

from pathlib import Path

import pytest

from app.pipeline.evidence import (
    BBox,
    CostRecord,
    EvidenceBundle,
    EvidenceSource,
    TextEvidence,
    VideoMeta,
)
from app.rules.matcher import Lexicon, Matcher

L3_PATH = Path(__file__).resolve().parents[1] / "app" / "rules" / "lexicon" / "L3_qualifications.yaml"


@pytest.fixture(scope="module")
def l3():
    return Lexicon.load_file(L3_PATH)


@pytest.fixture(scope="module")
def matcher(l3):
    return Matcher(l3)


def _bundle(text: str) -> EvidenceBundle:
    return EvidenceBundle(
        review_id="t",
        video=VideoMeta(path="t.mp4", duration=30.0, fps=30.0, width=1080, height=1920),
        evidences=[TextEvidence(
            id="ocr1", source=EvidenceSource.OCR, text=text,
            t_start=1.0, t_end=3.0,
            bbox=BBox(x=0.1, y=0.4, w=0.5, h=0.08),
        )],
        cost=CostRecord(),
    )


def test_l3_meta_and_scale(l3):
    assert l3.reviewed_by_legal is False
    terms = {e.term for e in l3.entries}
    assert {"发明专利", "3C认证", "独家授权", "国食健字"} <= terms
    assert len(l3.entries) >= 15


def test_every_l3_term_carries_materials_and_real_law(l3):
    for e in l3.entries:
        assert e.level == "L3"
        assert e.required_materials, e.term
        assert e.law_ref and "广告法" in e.law_ref
        assert e.law_text.strip(), e.term  # 不许喂空法条给 LLM


def test_patent_hit_carries_material_list(matcher):
    hits = matcher.match_bundle(_bundle("本品获国家发明专利，销量长红"))
    hit = next(h for h in hits if h.matched_text == "发明专利")
    assert hit.entry.level == "L3"
    payload = hit.to_llm_payload()
    materials = payload["需核验材料"]
    assert any("专利证书" in m for m in materials)
    assert payload["法律依据"]


def test_health_food_qualification_scoped_to_industry(l3):
    entry = next(e for e in l3.entries if e.term == "国食健字")
    assert not entry.applies_to("game")
    assert entry.applies_to("health_food")


def test_l3_merges_into_default_matcher():
    full = Matcher(Lexicon.load_dir())
    assert any(e.level == "L3" and e.required_materials for e in full.lexicon.entries)
    assert any(e.level == "L1" for e in full.lexicon.entries)
