"""字幕跨帧合并测试。

合并条件是「文本相似 + 空间重叠 + 时间邻接」三重的，
这里逐条验证：任意去掉一条都会产生什么错误。
"""

import pytest

from app.config import PipelineSettings
from app.pipeline.evidence import BBox, EvidenceSource, TextEvidence, WordTiming
from app.pipeline.merge import merge_ocr


@pytest.fixture
def cfg() -> PipelineSettings:
    return PipelineSettings()


def _ocr(uid, text, t0, t1, bbox=(0.30, 0.80, 0.40, 0.06), frame=0, conf=0.9, font=None):
    x, y, w, h = bbox
    return TextEvidence(
        id=uid, source=EvidenceSource.OCR, text=text,
        t_start=t0, t_end=t1,
        bbox=BBox(x=x, y=y, w=w, h=h),
        font_scale=h if font is None else font,
        confidence=conf, frame_ids=[frame],
    )


def _asr(uid, text, t0, t1):
    return TextEvidence(
        id=uid, source=EvidenceSource.ASR, text=text, t_start=t0, t_end=t1,
        word_timings=[WordTiming(text=c, t_start=t0, t_end=t1) for c in text],
    )


# ── 基本合并 ──────────────────────────────────────────────────


def test_same_text_across_frames_merges_into_one(cfg):
    """同一条花字跨 3 帧 → 合并成 1 条，时长是三帧的总跨度。

    不合并的话报告里会出现三条内容重复的风险，
    且每条时长都只有 0.5 秒——L4 显著性判定会被彻底带偏。
    """
    evs = [
        _ocr("a", "本品不能代替药物", 5.0, 5.5, frame=1),
        _ocr("b", "本品不能代替药物", 5.5, 6.0, frame=2),
        _ocr("c", "本品不能代替药物", 6.0, 6.5, frame=3),
    ]
    merged = merge_ocr(evs, cfg)
    assert len(merged) == 1
    m = merged[0]
    assert m.text == "本品不能代替药物"
    assert m.t_start == pytest.approx(5.0)
    assert m.t_end == pytest.approx(6.5)
    assert m.duration == pytest.approx(1.5)
    assert m.frame_ids == [1, 2, 3], "必须保留全部溯源帧，报告要靠它出证据截图"


# ── 三重条件各自的必要性 ──────────────────────────────────────


def test_same_frame_blocks_never_merge(cfg):
    """同一帧里的两个文本块必然是画面上不同的两处，绝不能合并。"""
    evs = [
        _ocr("top", "限时特惠", 3.0, 4.0, bbox=(0.3, 0.10, 0.4, 0.06), frame=7),
        _ocr("bot", "限时特惠", 3.0, 4.0, bbox=(0.3, 0.82, 0.4, 0.06), frame=7),
    ]
    assert len(merge_ocr(evs, cfg)) == 2


def test_different_text_same_position_does_not_merge(cfg):
    """同一位置先后出现的两条不同文案 → 两条风险，不能并成一条。

    只看空间重叠就会犯这个错。
    """
    evs = [
        _ocr("a", "全网销量第一", 3.0, 4.0, frame=1),
        _ocr("b", "限时特惠进行中", 4.0, 5.0, frame=2),
    ]
    assert len(merge_ocr(evs, cfg)) == 2


def test_same_text_far_apart_does_not_merge(cfg):
    """同一句话在片头片尾各出现一次 → 是两次独立出现，报告里要分别标注。

    只看文本相似就会把它们并成一条横跨全片的风险。
    """
    evs = [
        _ocr("a", "本品不能代替药物", 1.0, 1.5, frame=1),
        _ocr("b", "本品不能代替药物", 25.0, 25.5, frame=90),
    ]
    merged = merge_ocr(evs, cfg)
    assert len(merged) == 2
    assert all(m.duration < 1.0 for m in merged), "两次出现各自都很短，不该被拼成长时段"


def test_overlapping_positions_pick_best_iou(cfg):
    """画面上两条位置相近的花字同时延续时，新证据要接到重叠最大的那条上。

    遇到第一条就接会串台——两条风险的时间区间都会错。
    """
    evs = [
        _ocr("t1", "买一送一", 1.0, 1.5, bbox=(0.10, 0.20, 0.30, 0.06), frame=1),
        _ocr("t2", "买一送一", 1.0, 1.5, bbox=(0.60, 0.20, 0.30, 0.06), frame=1),
        _ocr("t2b", "买一送一", 1.5, 2.0, bbox=(0.61, 0.20, 0.30, 0.06), frame=2),
    ]
    merged = merge_ocr(evs, cfg)
    assert len(merged) == 2
    right = max(merged, key=lambda m: m.bbox.x)
    left = min(merged, key=lambda m: m.bbox.x)
    assert right.frame_ids == [1, 2], "第三条应接到右侧那条上"
    assert left.frame_ids == [1]


# ── 文本选择 ──────────────────────────────────────────────────


def test_fade_in_partial_read_merges_and_keeps_full_text(cfg):
    """花字淡入时边缘帧只识别出片段 → 应合并，且正式文本取完整的那条。"""
    evs = [
        _ocr("a", "本品不能代", 5.0, 5.3, frame=1),
        _ocr("b", "本品不能代替药物", 5.3, 5.8, frame=2),
        _ocr("c", "本品不能代替药物", 5.8, 6.3, frame=3),
    ]
    merged = merge_ocr(evs, cfg)
    assert len(merged) == 1
    assert merged[0].text == "本品不能代替药物"


def test_ocr_jitter_uses_modal_text(cfg):
    """个别帧识别错字 → 取众数，不被单帧抖动带偏。"""
    evs = [
        _ocr("a", "本品不能代替药物", 5.0, 5.5, frame=1),
        _ocr("b", "本品不能代誓药物", 5.5, 6.0, frame=2, conf=0.99),  # 置信度更高但是错的
        _ocr("c", "本品不能代替药物", 6.0, 6.5, frame=3),
    ]
    merged = merge_ocr(evs, cfg)
    assert len(merged) == 1
    assert merged[0].text == "本品不能代替药物", "取众数才抗得住单帧抖动；取最高置信度会选错"


def test_font_scale_uses_median_not_edge_frame(cfg):
    """字号取中位数：淡入淡出时边缘帧的框偏小，用它判显著性会冤枉合规素材。"""
    evs = [
        _ocr("a", "本品不能代替药物", 5.0, 5.5, frame=1, font=0.010),  # 淡入，框偏小
        _ocr("b", "本品不能代替药物", 5.5, 6.0, frame=2, font=0.050),
        _ocr("c", "本品不能代替药物", 6.0, 6.5, frame=3, font=0.052),
    ]
    merged = merge_ocr(evs, cfg)
    assert merged[0].font_scale == pytest.approx(0.050)


# ── 边界 ──────────────────────────────────────────────────────


def test_asr_passes_through_untouched(cfg):
    """ASR 不参与合并——合并会破坏字级时间戳与文本的对应关系。"""
    asr = _asr("s1", "本品采用国家级配方", 1.0, 3.0)
    ocr = [_ocr("o1", "限时特惠", 2.0, 2.5, frame=1)]
    merged = merge_ocr([asr] + ocr, cfg)

    kept = [e for e in merged if e.source == EvidenceSource.ASR]
    assert len(kept) == 1
    assert kept[0].text == asr.text
    assert len(kept[0].word_timings) == len(asr.text)


def test_empty_input(cfg):
    assert merge_ocr([], cfg) == []


def test_merge_output_is_time_sorted(cfg):
    evs = [
        _ocr("c", "第三条", 8.0, 8.5, bbox=(0.3, 0.5, 0.3, 0.06), frame=30),
        _ocr("a", "第一条", 1.0, 1.5, bbox=(0.3, 0.1, 0.3, 0.06), frame=1),
        _ocr("b", "第二条", 4.0, 4.5, bbox=(0.3, 0.3, 0.3, 0.06), frame=15),
    ]
    merged = merge_ocr(evs, cfg)
    assert [m.text for m in merged] == ["第一条", "第二条", "第三条"]
