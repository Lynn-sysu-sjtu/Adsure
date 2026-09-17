"""违禁词匹配测试。

锁三件事：
  1. AC 自动机的索引口径（字符 vs 字节）—— 中文下搞错会让所有时间戳静默偏移
  2. 白名单抑制真的生效 —— 否则「第一时间发货」会被报成违规，误报炸库
  3. ASR / OCR 的匹配语义分开 —— 拼接与否直接决定漏检和假命中
"""

import pytest

from app.pipeline.evidence import (
    BBox,
    CostRecord,
    EvidenceBundle,
    EvidenceSource,
    TextEvidence,
    VideoMeta,
    WordTiming,
)
from app.rules.matcher import Lexicon, Matcher, _Automaton


@pytest.fixture(scope="module")
def lexicon() -> Lexicon:
    return Lexicon.load_dir()


@pytest.fixture(scope="module")
def matcher(lexicon: Lexicon) -> Matcher:
    return Matcher(lexicon)


def _bundle(evidences: list[TextEvidence]) -> EvidenceBundle:
    return EvidenceBundle(
        review_id="test",
        video=VideoMeta(path="test.mp4", duration=30.0, fps=30.0, width=1920, height=1080),
        evidences=list(evidences),
        cost=CostRecord(),
    )


def _asr(uid: str, text: str, t_start: float, char_dur: float = 0.2) -> TextEvidence:
    timings, t = [], t_start
    for ch in text:
        timings.append(WordTiming(text=ch, t_start=t, t_end=t + char_dur))
        t += char_dur
    return TextEvidence(
        id=uid, source=EvidenceSource.ASR, text=text,
        t_start=t_start, t_end=t, word_timings=timings,
    )


def _ocr(uid: str, text: str, t_start: float, t_end: float, bbox=(0.1, 0.8, 0.5, 0.06)) -> TextEvidence:
    x, y, w, h = bbox
    return TextEvidence(
        id=uid, source=EvidenceSource.OCR, text=text,
        t_start=t_start, t_end=t_end,
        bbox=BBox(x=x, y=y, w=w, h=h), font_scale=h,
    )


# ── AC 自动机索引口径 ─────────────────────────────────────────


def test_automaton_reports_character_indexes():
    """AC 自动机必须返回**字符**索引。

    ahocorasick_rs 在不同版本下可能返回字节索引，中文一字三字节，
    口径错了时间戳会静默偏移。_Automaton 的自检就是防这个。
    """
    ac = _Automaton(["国家级", "最好"])
    text = "这个产品是国家级配方最好用"
    matches = ac.find(text)
    assert matches, "自动机没有命中，词匹配不可信"
    for _, start, end in matches:
        # 用返回的 offset 切片，必须切出真正的词面
        assert text[start:end] in {"国家级", "最好"}, (
            f"offset 口径错误：text[{start}:{end}]={text[start:end]!r}"
        )


def test_automaton_empty_patterns():
    assert _Automaton([]).find("任意文本") == []


# ── 词库自身 ──────────────────────────────────────────────────


def test_lexicon_loads(lexicon: Lexicon):
    assert len(lexicon.entries) > 30
    for e in lexicon.entries:
        assert e.term, "词面不能为空"
        assert e.law_ref, f"{e.term} 缺法条出处"
        assert e.law_text, f"{e.term} 缺法条原文 —— 空法条会让 LLM 自己编"


def test_lexicon_no_duplicate_terms(lexicon: Lexicon):
    terms = [e.term for e in lexicon.entries]
    assert len(terms) == len(set(terms)), "存在重复词条"


def test_whitelist_has_no_dead_config(lexicon: Lexicon):
    """每条白名单短语必须至少包含一个词面，否则永远不会被触发，是死配置。

    这条不变式写在 L1_absolute.yaml 的注释里，这里是它的守卫。
    """
    terms = [e.term for e in lexicon.entries]
    all_wl = list(lexicon.global_whitelist)
    for e in lexicon.entries:
        all_wl.extend(e.whitelist_contexts)

    dead = [w for w in all_wl if not any(t in w for t in terms)]
    assert not dead, f"以下白名单短语不含任何词面，是死配置: {dead}"


# ── 白名单抑制 ────────────────────────────────────────────────


def test_whitelist_suppresses_time_order_usage(matcher: Matcher):
    """「第一时间」是时间顺序表述，执法指南明确豁免，不得报风险。"""
    bundle = _bundle([_asr("a1", "我们承诺第一时间为您发货", 0.0)])
    hits = matcher.match_bundle(bundle)
    assert not any(h.matched_text == "第一" for h in hits), (
        f"「第一时间」被误报: {[(h.matched_text, h.context) for h in hits]}"
    )


def test_whitelist_suppresses_latest_model(matcher: Matcher):
    """「最新款」是时间描述，不是质量断言。"""
    bundle = _bundle([_asr("a1", "这是今年的最新款上市了", 0.0)])
    hits = matcher.match_bundle(bundle)
    assert not any(h.matched_text == "最新" for h in hits)


def test_flags_real_superlative(matcher: Matcher):
    """「第一品牌」是排名断言，必须报出来。"""
    bundle = _bundle([_asr("a1", "本产品是行业第一品牌值得信赖", 0.0)])
    hits = matcher.match_bundle(bundle)
    assert any("第一" in h.matched_text for h in hits), "「第一品牌」漏检"


def test_leftmost_longest_wins(matcher: Matcher):
    """命中「最高级」时不应该同时报「最高」—— 词库场景总是取最长匹配。"""
    bundle = _bundle([_asr("a1", "采用最高级材料制造", 0.0)])
    hits = matcher.match_bundle(bundle)
    matched = {h.matched_text for h in hits}
    assert "最高级" in matched
    assert "最高" not in matched


# ── 时间戳定位（端到端）───────────────────────────────────────


def test_asr_hit_carries_word_level_timestamp(matcher: Matcher):
    """命中必须带**词级**时间，而不是整句时间。这是整个产品的立身之本。"""
    # 逐字 0.2 秒，"国家级" 是第 4-6 字 → 10.8s ~ 11.4s
    bundle = _bundle([_asr("a1", "本品采用国家级配方", t_start=10.0, char_dur=0.2)])
    hits = [h for h in matcher.match_bundle(bundle) if h.matched_text == "国家级"]
    assert len(hits) == 1, "国家级漏检或重复命中"

    hit = hits[0]
    assert hit.t_start == pytest.approx(10.8, abs=1e-6)
    assert hit.t_end == pytest.approx(11.4, abs=1e-6)
    assert hit.t_start > 10.0, "退化成整句时间了，词级定位没生效"


def test_asr_cross_sentence_hit_is_found(matcher: Matcher):
    """违禁词横跨 ASR 切出的两句时不能漏检 —— 句子边界是识别产物，不是语义边界。"""
    bundle = _bundle([
        _asr("a1", "本品是国家", t_start=5.0),
        _asr("a2", "级配方效果好", t_start=6.0),
    ])
    hits = [h for h in matcher.match_bundle(bundle) if h.matched_text == "国家级"]
    assert len(hits) == 1, "跨句违禁词漏检"
    assert hits[0].t_start == pytest.approx(5.6, abs=1e-6)
    assert hits[0].t_end == pytest.approx(6.2, abs=1e-6)


def test_context_does_not_bleed_across_long_pause(matcher: Matcher):
    """相隔十几秒的两句话不能拼成一段上下文。

    报告里的「上下文」是给法务做判断的证据。若把 3 秒和 20 秒的两句
    拼在一起展示，读的人会以为那是一口气说下来的话——这是在伪造证据形态。
    跨句匹配只应发生在连续语流内部。
    """
    bundle = _bundle([
        _asr("a1", "本品采用国家级配方", t_start=3.0),
        _asr("a2", "上市以来销量第一值得信赖", t_start=20.0),
    ])
    hits = matcher.match_bundle(bundle)

    first = next(h for h in hits if h.matched_text == "国家级")
    assert "销量第一" not in first.context, (
        f"上下文串到了 17 秒之后的另一句：{first.context}"
    )
    assert "本品采用" in first.context

    later = next(h for h in hits if h.matched_text == "销量第一")
    assert "国家级" not in later.context
    assert later.t_start > 20.0, "后一句的命中时间必须落在它自己的时段内"


def test_contiguous_speech_still_joins(matcher: Matcher):
    """紧挨着的两句仍要拼接——否则跨句违禁词会漏检。分段不能把这个能力砍掉。"""
    bundle = _bundle([
        _asr("a1", "本品是国家", t_start=5.0),
        _asr("a2", "级配方效果好", t_start=6.0),   # 与上句无间隔
    ])
    assert any(h.matched_text == "国家级" for h in matcher.match_bundle(bundle))


# ── OCR 逐条匹配 ──────────────────────────────────────────────


def test_ocr_blocks_are_not_concatenated(matcher: Matcher):
    """画面上两块独立文字不能拼起来匹配，否则会造出现实中不存在的违规。

    「全网销量第一」在上、「品牌直供」在下，是两处独立花字，
    拼接会凭空造出「第一品牌」——报告里写一句根本没出现过的话，是硬伤。
    """
    bundle = _bundle([
        _ocr("o1", "全网销量第一", 3.0, 5.0, bbox=(0.1, 0.2, 0.5, 0.08)),
        _ocr("o2", "品牌直供", 3.0, 5.0, bbox=(0.1, 0.7, 0.4, 0.08)),
    ])
    hits = matcher.match_bundle(bundle)
    assert not any(h.matched_text == "第一品牌" for h in hits), "OCR 块被错误拼接"
    assert any("第一" in h.matched_text for h in hits), "「销量第一」本身应当命中"


def test_ocr_hit_carries_bbox_for_salience(matcher: Matcher):
    """OCR 命中必须带 bbox 与 font_scale —— L4 显著性核查全靠它们。"""
    bundle = _bundle([_ocr("o1", "国家级认证", 3.0, 5.0, bbox=(0.75, 0.92, 0.2, 0.02))])
    hits = matcher.match_bundle(bundle)
    assert hits
    hit = hits[0]
    assert hit.bbox is not None
    assert hit.font_scale == pytest.approx(0.02)
    assert hit.bbox.near_edge(margin=0.08), "右下角小字应当被判定为贴边"


# ── LLM 载荷 ──────────────────────────────────────────────────


def test_llm_payload_carries_law_text_not_conclusion(matcher: Matcher):
    """喂给 LLM 的载荷必须含法条原文，且**不含结论** —— 定性是 LLM 的活，不是词库的。"""
    bundle = _bundle([_asr("a1", "本品采用国家级配方", 10.0)])
    hits = [h for h in matcher.match_bundle(bundle) if h.matched_text == "国家级"]
    payload = hits[0].to_llm_payload()

    assert payload["法条原文"], "法条原文为空，等于放任 LLM 自己编"
    assert "第九条" in payload["法律依据"]
    assert payload["上下文原文"], "没有上下文，LLM 无法区分「最新款」与「最好用」"
    for key in payload:
        assert key not in {"结论", "是否违规", "风险等级"}, "词库层不得下结论"
