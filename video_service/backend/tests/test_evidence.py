"""证据模型测试。

重点锁住**字符 offset → 时间戳**这条换算链路。
它错了不会抛异常，只会让报告悄悄指向错误的秒数 —— 这是本项目最危险的失败模式。
"""

import pytest

from app.pipeline.evidence import (
    BBox,
    EvidenceSource,
    TextEvidence,
    TranscriptIndex,
    WordTiming,
)


def _asr_unit(uid: str, text: str, t_start: float, char_dur: float = 0.2) -> TextEvidence:
    timings = []
    t = t_start
    for ch in text:
        timings.append(WordTiming(text=ch, t_start=t, t_end=t + char_dur))
        t += char_dur
    return TextEvidence(
        id=uid,
        source=EvidenceSource.ASR,
        text=text,
        t_start=t_start,
        t_end=t,
        word_timings=timings,
    )


# ── BBox ──────────────────────────────────────────────────────


def test_bbox_iou_identical():
    b = BBox(x=0.1, y=0.1, w=0.2, h=0.2)
    assert b.iou(b) == pytest.approx(1.0)


def test_bbox_iou_disjoint():
    a = BBox(x=0.0, y=0.0, w=0.1, h=0.1)
    b = BBox(x=0.5, y=0.5, w=0.1, h=0.1)
    assert a.iou(b) == 0.0


def test_bbox_near_edge():
    corner = BBox(x=0.01, y=0.9, w=0.08, h=0.03)
    center = BBox(x=0.4, y=0.4, w=0.2, h=0.1)
    assert corner.near_edge(margin=0.08) is True
    assert center.near_edge(margin=0.08) is False


# ── 字级时间戳换算 ────────────────────────────────────────────


def test_resolve_time_pinpoints_word():
    """「国家级」这三个字应当定位到它们自己的时间，而不是整句的时间。

    这正是产品承诺「第 13.4 秒说了国家级」与竞品「这句话在 12-15 秒」的差别。
    """
    unit = _asr_unit("a1", "本品采用国家级配方", t_start=10.0, char_dur=0.2)
    # "国家级" 是第 4-6 个字（0-based），切片 [4:7]
    assert unit.text[4:7] == "国家级"

    t0, t1 = unit.resolve_time(4, 7)
    assert t0 == pytest.approx(10.8, abs=1e-6)
    assert t1 == pytest.approx(11.4, abs=1e-6)
    # 必须严格窄于整句区间，否则等于没定位
    assert t0 > unit.t_start
    assert t1 < unit.t_end


def test_resolve_time_without_word_timings_falls_back():
    """OCR 没有字级时间戳，整块文字共享一个区间 —— 这是正确行为，不是降级。"""
    unit = TextEvidence(
        id="o1",
        source=EvidenceSource.OCR,
        text="国家级配方",
        t_start=3.0,
        t_end=6.5,
        bbox=BBox(x=0.1, y=0.8, w=0.5, h=0.06),
    )
    assert unit.resolve_time(0, 3) == (3.0, 6.5)


# ── TranscriptIndex ───────────────────────────────────────────


def test_transcript_index_joins_without_separator():
    """ASR 必须无分隔符拼接，否则横跨两句的违禁词会漏检。"""
    units = [_asr_unit("a1", "本品是国家", 5.0), _asr_unit("a2", "级配方很好", 6.0)]
    index = TranscriptIndex(units)
    assert index.document == "本品是国家级配方很好"
    assert "国家级" in index.document


def test_transcript_index_cross_unit_timestamps():
    """跨句命中的**起止时间必须分别取自两条证据**。

    只用起始那条会让结束时间偏早，报告里的时间区间就是错的。
    这是一个不会报错、只会悄悄给出错误秒数的坑。
    """
    units = [_asr_unit("a1", "本品是国家", 5.0), _asr_unit("a2", "级配方很好", 6.0)]
    index = TranscriptIndex(units)

    start = index.document.index("国家级")
    end = start + len("国家级")
    resolved = index.resolve(start, end)
    assert resolved is not None
    unit, t0, t1 = resolved

    assert unit.id == "a1"                      # 归属起始那条
    assert t0 == pytest.approx(5.6, abs=1e-6)   # "国" 在 a1 里的开始
    assert t1 == pytest.approx(6.2, abs=1e-6)   # "级" 在 a2 里的结束
    assert t1 > units[0].t_end                  # 关键：结束时间越过了第一条的边界


def test_transcript_index_locate_out_of_range():
    units = [_asr_unit("a1", "测试", 0.0)]
    index = TranscriptIndex(units)
    assert index.resolve(999, 1000) is None
