"""Provider 抽象层测试。

锁三件事：
  1. 能力闸门 —— 不支持字级时间戳的 ASR 必须在初始化时就被拒绝
  2. 成本闸门 —— 超红线要抛错，**不能静默截断**
  3. span 回填 —— 去重帧代表的时间跨度必须覆盖单帧时刻
"""

import pytest

from app.pipeline.evidence import EvidenceSource
from app.pipeline.frames import SampledFrame
from app.pipeline.providers.base import (
    ASRCapabilities,
    ASRProvider,
    CapabilityError,
    CostLimitExceeded,
    to_normalized_bbox,
)
from app.pipeline.providers.mock import (
    MockASRProvider,
    MockOCRProvider,
    MockVLMProvider,
    ScriptedEntity,
    ScriptedTextBlock,
    ScriptedUtterance,
)


def _frame(fid: int, t: float, span: tuple[float, float] | None = None) -> SampledFrame:
    s, e = span or (t, t)
    return SampledFrame(frame_id=fid, t=t, is_scene_key=False, span_start=s, span_end=e)


# ── 能力闸门 ──────────────────────────────────────────────────


def test_asr_without_word_timestamps_is_rejected():
    """字级时间戳是硬指标。带病上路的后果是整份报告的秒数全不可用，
    而且不会报错 —— 所以必须在初始化时就拦下来。"""

    class SegmentLevelASR(ASRProvider):
        name = "segment-only"

        def capabilities(self):
            return ASRCapabilities(word_timestamps=False)

        def transcribe(self, audio_path, hotwords=None):
            return []

    with pytest.raises(CapabilityError, match="字级时间戳"):
        SegmentLevelASR()


def test_mock_asr_passes_capability_gate():
    provider = MockASRProvider()
    assert provider.capabilities().word_timestamps is True


# ── ASR 输出 ──────────────────────────────────────────────────


def test_mock_asr_emits_word_timings():
    provider = MockASRProvider([ScriptedUtterance(text="国家级配方", t_start=2.0, char_duration=0.2)])
    evidences = provider.transcribe(audio_path=None)  # mock 不读文件

    assert len(evidences) == 1
    ev = evidences[0]
    assert ev.source == EvidenceSource.ASR
    assert len(ev.word_timings) == len("国家级配方"), "字级时间戳必须覆盖每个字"
    assert ev.word_timings[0].t_start == pytest.approx(2.0)
    assert ev.bbox is None, "语音没有空间位置"


# ── 成本闸门 ──────────────────────────────────────────────────


def test_ocr_cost_limit_raises_not_truncates():
    """超红线必须抛错。

    静默截断会让报告看起来「审完了」，实际后半段视频根本没看 ——
    这比直接报错危险得多，是会让客户被罚的那种危险。
    """
    provider = MockOCRProvider(max_calls=2)
    frames = [_frame(i, i * 0.5) for i in range(3)]

    with pytest.raises(CostLimitExceeded, match="超过单条视频上限"):
        provider.recognize(frames, img_w=1920, img_h=1080)

    assert provider.calls_used == 0, "抛错前不应产生任何计费调用"


def test_vlm_cost_limit_counts_batches_not_frames():
    """VLM 按批计费，8 帧 / 每批 4 = 2 次调用，不该按 8 次算。"""
    provider = MockVLMProvider(max_calls=2)
    frames = [_frame(i, i * 1.0) for i in range(8)]
    provider.scan(frames, batch_size=4)
    assert provider.calls_used == 2


# ── span 回填（去重的关键后半程）──────────────────────────────


def test_ocr_evidence_uses_frame_span_not_instant():
    """OCR 证据的时间区间必须用代表帧的 span，而不是单帧时刻。

    一条花字连续出现 3 秒 = 6 个采样帧，去重后只留 1 帧送 OCR。
    若证据只记那一帧的时刻，报告里的时间区间会缩成一个点，
    且 L4「免责声明只显示了 0.5 秒」的时长判定直接失效 ——
    时长信息恰恰藏在被丢掉的那些重复帧里。
    """
    frame = _frame(120, t=5.0, span=(5.0, 8.0))
    provider = MockOCRProvider([ScriptedTextBlock(text="效果因人而异", frame_index=0)])

    evidences = provider.recognize([frame], img_w=1920, img_h=1080)
    assert len(evidences) == 1
    ev = evidences[0]

    assert ev.t_start == pytest.approx(5.0)
    assert ev.t_end == pytest.approx(8.0), "span 没有回填，时长信息丢了"
    assert ev.duration == pytest.approx(3.0)
    assert ev.frame_ids == [120], "必须能溯源到具体帧，否则报告出不了证据截图"


# ── VLM 幻觉防线 ──────────────────────────────────────────────


def test_vlm_results_are_always_marked_for_human_review():
    """VLM 单独发现的 IP 一律标「疑似待人工确认」，不进正式风险清单。

    VLM 会把普通老鼠说成米奇。IP 误报的代价很高 ——
    会让法务白跑一趟去要一份根本不需要的授权书，信任一次就崩。
    """
    provider = MockVLMProvider([
        ScriptedEntity(
            entity_name="米奇老鼠",
            entity_type="cartoon_character",
            rights_holder="The Walt Disney Company",
            frame_index=0,
        )
    ])
    results = provider.scan([_frame(10, 3.0, span=(3.0, 5.0))], batch_size=4)

    assert len(results) == 1
    assert results[0].needs_human_review is True, "VLM 结果必须强制标记待人工确认"
    assert results[0].source == EvidenceSource.VLM


# ── 坐标换算 ──────────────────────────────────────────────────


def test_normalized_bbox_basic():
    bbox = to_normalized_bbox(192, 108, 384, 54, img_w=1920, img_h=1080)
    assert bbox.x == pytest.approx(0.1)
    assert bbox.y == pytest.approx(0.1)
    assert bbox.w == pytest.approx(0.2)
    assert bbox.h == pytest.approx(0.05)


def test_normalized_bbox_clamps_out_of_range():
    """部分 OCR 会返回略微越界的框，直接构造 BBox 会被 pydantic 拒绝，
    让整条视频失败 —— 不值得，夹紧即可。"""
    bbox = to_normalized_bbox(-10, -10, 2000, 1200, img_w=1920, img_h=1080)
    assert 0.0 <= bbox.x <= 1.0
    assert 0.0 <= bbox.y <= 1.0
    assert bbox.x + bbox.w <= 1.0 + 1e-9
    assert bbox.y + bbox.h <= 1.0 + 1e-9
