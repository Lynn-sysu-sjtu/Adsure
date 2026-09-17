"""本地开源 Provider 测试（faster-whisper / RapidOCR）。

这两个 Provider 是"真实视频能不能进来"的落点，锁四类不变式：

  1. 能力声明必须与实测一致 —— 声明错了，能力闸门就成了摆设
  2. 字级时间戳必须覆盖全文 —— 否则 offset→时间戳换算会退化，报告秒数不可用
  3. 置信度只透传模型真给的数 —— 补 1.0 等于替模型声称它没声称过的确定性
  4. 可复现 —— 同一素材两次审核给出不同证据，法务没法用，也没法追责

模型对象一律用假的注入，**测试不下载模型、不联网**。
"""

import pytest

from app.pipeline.evidence import EvidenceSource
from app.pipeline.frames import SampledFrame
from app.pipeline.providers.base import ocr_budget_for
from app.pipeline.providers.local import LocalRapidOCR, LocalWhisperASR


# ── 假模型 ────────────────────────────────────────────────────


class _Word:
    def __init__(self, word, start, end, probability=None):
        self.word, self.start, self.end, self.probability = word, start, end, probability


class _Seg:
    def __init__(self, start, end, words):
        self.start, self.end, self.words = start, end, words


class _FakeWhisper:
    """记录调用参数，方便断言可复现设置真的传下去了。"""

    def __init__(self, segments):
        self.segments = segments
        self.kwargs = None

    def transcribe(self, path, **kwargs):
        self.kwargs = kwargs
        return iter(self.segments), object()


def _asr(segments) -> LocalWhisperASR:
    p = LocalWhisperASR(model_size="small")
    p._model = _FakeWhisper(segments)
    return p


def _ocr(result, max_calls: int = 20) -> LocalRapidOCR:
    p = LocalRapidOCR(max_calls=max_calls)
    p._ocr = lambda src: (result, [0.0])
    return p


def _frame(fid=1, t=2.0, span=(2.0, 5.0), path="frames/frame_000001.jpg") -> SampledFrame:
    from pathlib import Path
    return SampledFrame(frame_id=fid, t=t, is_scene_key=False,
                        span_start=span[0], span_end=span[1],
                        path=Path(path) if path else None)


# ── 导入不应拉起重依赖 ────────────────────────────────────────


def test_module_imports_without_model_packages():
    """faster_whisper / rapidocr 必须是懒加载。

    否则任何 import 本模块的地方（包括这份测试、包括找法层）
    都会被迫装上模型依赖 —— 与 frames.py 不拉 opencv 是同一条原则。
    """
    import app.pipeline.providers.local as m
    assert m.LocalWhisperASR and m.LocalRapidOCR


# ── 能力闸门 ──────────────────────────────────────────────────


def test_whisper_declares_word_timestamps():
    """声明 True 是有实测依据的：中文逐字返回 start/end/probability。
    声明错了，基类的能力闸门就形同虚设。"""
    p = LocalWhisperASR(model_size="small")     # 构造即过闸门，不加载模型
    assert p.capabilities().word_timestamps is True


def test_rapidocr_declares_bbox():
    """bbox 是 L4 显著性核查的唯一输入，拿不到这条产品的差异化就没了。"""
    p = LocalRapidOCR(max_calls=20)
    caps = p.capabilities()
    assert caps.bbox is True and caps.confidence is True


# ── ASR：字级时间戳 ───────────────────────────────────────────


def test_asr_word_timings_cover_whole_text():
    """word_timings 必须逐字覆盖 text。

    覆盖不全时，evidence.py 的字符游标会落到没有时间戳的位置，
    退回整条区间 —— 报告从"第 13.4 秒"退化成"这句话大概在 12-15 秒"，
    正是本产品要消灭的东西。
    """
    ev = _asr([_Seg(1.0, 2.0, [
        _Word("国", 1.0, 1.2, .9), _Word("家", 1.2, 1.4, .9),
        _Word("级", 1.4, 1.6, .8), _Word("配", 1.6, 1.8, .9),
        _Word("方", 1.8, 2.0, .9),
    ])]).transcribe("dummy.wav")

    assert len(ev) == 1
    e = ev[0]
    assert e.text == "国家级配方"
    assert "".join(w.text for w in e.word_timings) == e.text, "字级时间戳没有覆盖全文"
    assert e.source == EvidenceSource.ASR
    assert e.bbox is None and e.font_scale is None, "语音没有空间位置"


def test_asr_interval_comes_from_word_timings_not_segment():
    """时间区间取首尾字，而不是段落自报的 start/end。

    whisper 的段落边界会包含前后静音，用它当证据区间会把
    "这句话说了多久"放大，L4 的时长判定跟着失真。
    """
    ev = _asr([_Seg(0.0, 9.9, [_Word("根", 3.0, 3.2, .9), _Word("治", 3.2, 3.5, .9)])]
              ).transcribe("dummy.wav")
    assert ev[0].t_start == pytest.approx(3.0)
    assert ev[0].t_end == pytest.approx(3.5)


def test_asr_drops_segments_without_word_timings():
    """没有字级时间戳的段落必须丢弃，不能降级成整段证据。

    留着它等于在报告里放一条定位不到词的"伪证据"，
    而读报告的人无从分辨哪条能改片、哪条不能。
    """
    ev = _asr([
        _Seg(0.0, 1.0, []),                                   # 无字级 → 丢
        _Seg(2.0, 2.4, [_Word("最", 2.0, 2.2, .8), _Word("好", 2.2, 2.4, .8)]),
    ]).transcribe("dummy.wav")

    assert len(ev) == 1 and ev[0].text == "最好"


# ── ASR：置信度诚实性 ────────────────────────────────────────


def test_asr_confidence_is_mean_of_real_word_probabilities():
    ev = _asr([_Seg(0, 1, [_Word("甲", 0, .5, 0.4), _Word("乙", .5, 1, 0.6)])]
              ).transcribe("dummy.wav")
    assert ev[0].confidence == pytest.approx(0.5)


def test_asr_confidence_is_none_when_model_gives_none():
    """模型没给概率就写 None，**绝不补 1.0**。

    补 1.0 等于替模型声称了它从没声称过的确定性；
    在一份要给法务看的证据里，这是编造数据质量。
    """
    ev = _asr([_Seg(0, 1, [_Word("甲", 0, .5, None), _Word("乙", .5, 1, None)])]
              ).transcribe("dummy.wav")
    assert ev[0].confidence is None


# ── ASR：可复现 ──────────────────────────────────────────────


def test_asr_uses_deterministic_decoding():
    """固定温度、关闭温度回退与上文条件。

    实测依据：低置信度音频（字级概率 0.2–0.5）开启回退时，
    同一段音频两次转写的分段数从 34 变成 57，证据条目对不上。
    法律判断要可复现 —— 与 LLM 层固定 temperature=0 是同一条原则。
    """
    p = _asr([_Seg(0, 1, [_Word("甲", 0, 1, .9)])])
    p.transcribe("dummy.wav")

    kw = p._model.kwargs
    assert kw["temperature"] == 0.0
    assert kw["condition_on_previous_text"] is False
    assert kw["word_timestamps"] is True


def test_asr_enables_vad_filter():
    """VAD 不是可选优化，是两个实测问题的共同解：

    1. 静音/纯音乐段会让 whisper 锁死在一个短语上反复输出，且**越重复越自信**
       （medium 档把一段音乐认成同一人名连出 5 段，置信度 0.91）——
       所以置信度不能当质量闸门，得先把无人声段切掉。
    2. 静音段还会让字级时间戳对齐直接崩（find_alignment 抛 IndexError），
       整条视频跟着失败。这是拿真实构造素材跑出来的，不是假想。
    """
    p = _asr([_Seg(0, 1, [_Word("甲", 0, 1, .9)])])
    p.transcribe("dummy.wav")
    assert p._model.kwargs["vad_filter"] is True


# ── OCR：坐标与字号 ──────────────────────────────────────────


def test_ocr_polygon_to_normalized_bbox_and_font_scale():
    """四点框折成轴对齐矩形并归一化；font_scale 取归一化高度。

    font_scale 是 L4「字号只占画面 1.8%」判定的唯一来源，
    算错会让"字太小"这条查不出来。
    """
    poly = [[192, 108], [576, 108], [576, 162], [192, 162]]   # 384x54 @1920x1080
    ev = _ocr([[poly, "本品不能代替药物", 0.93]]).recognize(
        [_frame()], img_w=1920, img_h=1080)

    assert len(ev) == 1
    e = ev[0]
    assert e.bbox.x == pytest.approx(0.1)
    assert e.bbox.y == pytest.approx(0.1)
    assert e.bbox.w == pytest.approx(0.2)
    assert e.bbox.h == pytest.approx(0.05)
    assert e.font_scale == pytest.approx(0.05)
    assert e.confidence == pytest.approx(0.93)
    assert e.source == EvidenceSource.OCR


def test_ocr_skips_blank_text():
    """空白识别结果不该变成证据 —— 它会在报告里占一条却什么都没说。"""
    poly = [[0, 0], [10, 0], [10, 10], [0, 10]]
    ev = _ocr([[poly, "   ", 0.9], [poly, "限时特惠", 0.95]]).recognize(
        [_frame()], img_w=1000, img_h=1000)
    assert [e.text for e in ev] == ["限时特惠"]


def test_ocr_span_is_backfilled_by_base_class():
    """去重帧代表的时间跨度必须回填到证据上。

    这条在基类里实现，但要确认本子类没有绕过它 ——
    时长信息藏在被去重丢掉的帧里，丢了 L4 的时长判定就失效。
    """
    poly = [[0, 0], [100, 0], [100, 40], [0, 40]]
    ev = _ocr([[poly, "全网销量第一", 0.99]]).recognize(
        [_frame(fid=7, t=2.0, span=(2.0, 5.0))], img_w=1000, img_h=1000)

    assert ev[0].t_start == pytest.approx(2.0)
    assert ev[0].t_end == pytest.approx(5.0)
    assert ev[0].frame_ids == [7]


def test_ocr_carries_provenance():
    """取证链：法务追问「这是哪个引擎认出来的、原图在哪」要答得上来，
    答不上来这条证据就不可采信。"""
    poly = [[0, 0], [50, 0], [50, 20], [0, 20]]
    ev = _ocr([[poly, "国家级", 0.97]]).recognize(
        [_frame(path="frames/frame_000042.jpg")], img_w=500, img_h=500)

    e = ev[0]
    assert e.provider == "local-rapidocr"
    assert "PP-OCR" in (e.provider_version or "")
    assert "frame_000042" in e.raw_ref.get("frame_path", "")


# ── 成本红线按时长折算 ───────────────────────────────────────


def test_ocr_budget_scales_with_duration():
    """红线是按 30 秒广告标定的，拿去卡 60 秒素材等于要求它的
    去重率翻倍 —— 那不是成本要求，是长度歧视。改成每秒成本恒定。"""
    assert ocr_budget_for(30.0, base=20) == 20
    assert ocr_budget_for(60.0, base=20) == 40
    assert ocr_budget_for(54.3, base=20) == 37     # 向上取整


def test_ocr_budget_never_below_base():
    """短素材不该被卡到不合理的低值：3 秒的片子不能只给 2 次 OCR。"""
    assert ocr_budget_for(3.0, base=20) == 20
    assert ocr_budget_for(0.0, base=20) == 20


def test_ocr_budget_still_catches_expensive_material():
    """放宽的是长度差异，不是成本本身。

    实测那条 54.3 秒快切广告去重后仍需 98 次 OCR，
    折算后的红线是 37 —— 依然会被拦下，这是对的：那是真的贵。
    """
    assert 98 > ocr_budget_for(54.3, base=20)


def test_ocr_frame_without_image_source_fails_loudly():
    """既无 path 又无内存图像时直接报错，不返回空列表。

    返回空列表会让这一帧"看起来审过了"，实际什么都没看 ——
    与成本超限要抛错而非静默截断是同一条理由。
    """
    p = _ocr([])
    with pytest.raises(ValueError, match="无法识别"):
        p.recognize([_frame(path=None)], img_w=100, img_h=100)
