"""双层 IP 检测融合测试（实施方案 v2 §5、坑 #6）。"""

import pytest

from app.ip.detector import (
    HitSource,
    IPDetector,
    IPHit,
    ReviewStatus,
    consolidate_hits,
)
from app.ip.library import load_library
from app.ip.prompts import SYSTEM_PROMPT, parse_vlm_response
from app.ip.vectors import PurePythonVectorIndex, VectorMeta
from app.pipeline.evidence import EntityType, EvidenceSource
from app.pipeline.frames import SampledFrame
from app.pipeline.providers.base import CostLimitExceeded
from app.pipeline.providers.mock import MockVLMProvider, ScriptedEntity

LIBRARY = load_library()


class ScriptedEmbedder:
    """按帧号返回预设向量的 SSCD 替身。"""

    name = "scripted-sscd"
    dim = 4

    def __init__(self, vec_by_id: dict[int, list[float]]):
        self.vec = vec_by_id

    def embed_frames(self, frames):
        return [self.vec[f.frame_id] for f in frames]


def frame(fid: int, t: float) -> SampledFrame:
    return SampledFrame(frame_id=fid, t=t, span_start=t, span_end=t + 1.0,
                        is_scene_key=True)


def mickey_index() -> PurePythonVectorIndex:
    idx = PurePythonVectorIndex(dim=4)
    idx.add([1.0, 0.0, 0.0, 0.0], VectorMeta("disney_mickey", "mickey_003.jpg"))
    return idx


def test_library_hit_is_confirmed_with_materials_and_ref():
    det = IPDetector(LIBRARY, mickey_index(), ScriptedEmbedder({0: [0.98, 0.1, 0.1, 0.0]}))
    res = det.detect([frame(0, 0.0)])
    assert len(res.confirmed) == 1
    h = res.confirmed[0]
    assert h.ip_id == "disney_mickey"
    assert h.match_ref == "mickey_003.jpg"
    assert h.score >= 0.9
    assert HitSource.LIBRARY in h.sources
    assert h.required_materials[0].endswith("官方授权书")
    assert h.is_pending is False
    ev = h.to_evidence()
    assert ev.source is EvidenceSource.IP_MATCH
    assert ev.needs_human_review is False


def test_library_miss_then_vlm_hit_is_forced_pending():
    vlm = MockVLMProvider([
        ScriptedEntity(entity_name="米奇老鼠", entity_type="cartoon_character",
                       rights_holder="The Walt Disney Company", frame_index=0),
    ])
    det = IPDetector(LIBRARY, mickey_index(),
                     ScriptedEmbedder({7: [0.0, 1.0, 0.0, 0.0]}), vlm=vlm)
    res = det.detect([frame(7, 5.0)])
    assert len(res.pending) == 1 and not res.confirmed
    h = res.pending[0]
    assert h.ip_id == "disney_mickey"          # VLM 报名字经名称表归一
    assert h.rights_holder.startswith("The Walt")
    assert h.required_materials                # 材料清单仍给出
    assert h.to_evidence().needs_human_review is True
    assert vlm.calls_used == 1


def test_vlm_generic_cartoon_is_pending_unresolved_not_confirmed():
    vlm = MockVLMProvider([
        ScriptedEntity(entity_name="原创卡通猫", entity_type="cartoon_character",
                       frame_index=0, confidence=0.99),
    ])
    det = IPDetector(LIBRARY, PurePythonVectorIndex(4), None, vlm=vlm)
    res = det.detect([frame(9, 1.0)])
    assert len(res.hits) == 1
    assert res.hits[0].is_pending
    assert res.confirmed == []                  # 高置信度也不能让长尾进正式清单
    assert res.hits[0].ip_id is None


def test_constructing_vlm_only_hit_with_confirmed_is_overridden():
    """坑 #6：基类强制置位，调用方（含子类思路）无法绕过。"""
    h = IPHit(
        ip_id="x", entity_name="x", entity_type=EntityType.OTHER,
        sources=frozenset({HitSource.VLM}),
        review_status=ReviewStatus.CONFIRMED,   # 试图强行确认
        t_start=0, t_end=1,
    )
    assert h.review_status is ReviewStatus.SUSPECTED_PENDING
    with pytest.raises(Exception):
        h.review_status = ReviewStatus.CONFIRMED


def test_cross_validation_merges_into_confirmed_span():
    # f2 底库未命中但 VLM 报「米奇老鼠」，f3 底库命中；间隔 ≤1.5s → 合并为 confirmed
    vlm = MockVLMProvider([
        ScriptedEntity(entity_name="米奇老鼠", entity_type="cartoon_character",
                       frame_index=0),
        ScriptedEntity(entity_name="米奇老鼠", entity_type="cartoon_character",
                       frame_index=1),
    ])
    emb = ScriptedEmbedder({
        1: [0.0, 1.0, 0.0, 0.0],   # 8.0s 孤立 VLM 命中
        2: [0.0, 1.0, 0.0, 0.0],   # 2.0s VLM
        3: [0.97, 0.1, 0.1, 0.0],  # 3.0s 底库命中
    })
    det = IPDetector(LIBRARY, mickey_index(), emb, vlm=vlm)
    res = det.detect([frame(1, 8.0), frame(2, 2.0), frame(3, 3.0)])
    by_span = {(round(h.t_start, 1)): h for h in res.hits}
    merged = by_span[2.0]
    assert merged.review_status is ReviewStatus.CONFIRMED
    assert HitSource.LIBRARY in merged.sources and HitSource.VLM in merged.sources
    assert merged.frame_ids == [2, 3]
    assert merged.t_end == 4.0
    assert merged.match_ref == "mickey_003.jpg"
    # 8.0s 的 VLM 命中与合并区间间隔 >1.5s，保持独立 pending
    assert by_span[8.0].is_pending


def test_consolidate_respects_gap():
    def hit(t0, t1, source=HitSource.LIBRARY):
        return IPHit(ip_id="a", entity_name="A", entity_type=EntityType.OTHER,
                     sources=frozenset({source}), review_status=ReviewStatus.CONFIRMED,
                     t_start=t0, t_end=t1)
    out = consolidate_hits([hit(0, 1), hit(3, 4)], max_gap_seconds=1.5)
    assert len(out) == 2


def test_library_hit_frames_skip_vlm_saving_calls():
    vlm = MockVLMProvider([])
    emb = ScriptedEmbedder({0: [0.99, 0, 0, 0]})
    det = IPDetector(LIBRARY, mickey_index(), emb, vlm=vlm)
    det.detect([frame(0, 0)])
    assert vlm.calls_used == 0


def test_vlm_cost_gate_still_fires():
    frames = [frame(i, float(i)) for i in range(20)]  # 20 帧 / 批 4 = 5 次 > 红线 4
    det = IPDetector(LIBRARY, PurePythonVectorIndex(4), None,
                     vlm=MockVLMProvider([], max_calls=4))
    with pytest.raises(CostLimitExceeded):
        det.detect(frames)


def test_unknown_index_ip_id_is_skipped():
    idx = PurePythonVectorIndex(4)
    idx.add([1.0, 0, 0, 0], VectorMeta("deleted_ip", "x.jpg"))
    det = IPDetector(LIBRARY, idx, ScriptedEmbedder({0: [1, 0, 0, 0]}))
    res = det.detect([frame(0, 0)])
    assert res.hits == []


def test_embedder_dim_mismatch_rejected():
    with pytest.raises(ValueError):
        IPDetector(LIBRARY, PurePythonVectorIndex(8), ScriptedEmbedder({}))


def test_prompt_offers_none_and_uncertainty_options():
    assert "无" in SYSTEM_PROMPT and "不确定" in SYSTEM_PROMPT
    assert "uncertainty" in SYSTEM_PROMPT and "frame_index" in SYSTEM_PROMPT


def test_parse_vlm_response_robustness():
    ok, unc = parse_vlm_response(
        '噪音 {"uncertainty": false, "entities": [{"frame_index": 1,'
        ' "ip_id": "disney_mickey", "name_cn": "米奇老鼠",'
        ' "entity_type": "cartoon_character", "bbox": [0.1,0.1,0.2,0.3],'
        ' "confidence": 0.9}]} 尾巴')
    assert len(ok) == 1 and ok[0]["frame_index"] == 1
    assert unc is False

    assert parse_vlm_response("我觉得可能有个什么东西") == ([], True)
    assert parse_vlm_response("") == ([], True)

    # 非法 bbox 降级为 None，不整条丢弃；非法 frame_index 整条丢弃
    ents, _ = parse_vlm_response(
        '{"entities":[{"frame_index":0,"name_cn":"A","entity_type":"other",'
        '"bbox":[0.9,0.9,0.5,0.5],"confidence":2},'
        '{"frame_index":-1,"name_cn":"B","entity_type":"other"}]}')
    assert ents[0]["bbox"] is None and ents[0]["confidence"] == 0.0
    assert len(ents) == 1


def test_vector_index_cosine_and_validation():
    idx = PurePythonVectorIndex(3)
    idx.add([1.0, 0, 0], VectorMeta("a", "1.jpg"))
    assert idx.search([0.9, 0.1, 0])[0].score > 0.99
    with pytest.raises(ValueError):
        idx.add([1, 0], VectorMeta("b", "2.jpg"))
    with pytest.raises(ValueError):
        idx.add([0, 0, 0], VectorMeta("b", "3.jpg"))
    assert PurePythonVectorIndex(3).search([1, 0, 0]) == []
