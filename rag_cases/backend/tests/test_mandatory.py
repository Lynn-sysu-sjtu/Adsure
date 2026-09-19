"""L4 必备要素与显著性核查测试。

这一层是产品差异化最强的地方，也是最容易做错的地方：
「没写」和「写了但太小」是两种完全不同的定性，整改方向也不同，
判错了会把客户带到错误的修改方向上。
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
from app.rules.mandatory import (
    MandatoryChecker,
    MandatoryStatus,
    load_requirements,
)

DISCLAIMER = "本品不能代替药物"


@pytest.fixture(scope="module")
def checker() -> MandatoryChecker:
    return MandatoryChecker()


def _bundle(evs):
    return EvidenceBundle(
        review_id="t",
        video=VideoMeta(path="t.mp4", duration=30.0, fps=30.0, width=1920, height=1080),
        evidences=list(evs),
        cost=CostRecord(),
    )


def _ocr(text, t0, t1, bbox=(0.30, 0.45, 0.40, 0.05), font=None, frame=1):
    x, y, w, h = bbox
    return TextEvidence(
        id=f"o{frame}", source=EvidenceSource.OCR, text=text,
        t_start=t0, t_end=t1,
        bbox=BBox(x=x, y=y, w=w, h=h),
        font_scale=h if font is None else font,
        frame_ids=[frame],
    )


def _asr(text, t0, t1):
    return TextEvidence(
        id="s1", source=EvidenceSource.ASR, text=text, t_start=t0, t_end=t1,
        word_timings=[WordTiming(text=c, t_start=t0, t_end=t1) for c in text],
    )


def _find(findings, req_id):
    got = [f for f in findings if f.requirement.id == req_id]
    assert got, f"未产出 {req_id} 的核查结论"
    return got[0]


# ── 词库自身 ──────────────────────────────────────────────────


def test_requirements_load_with_law_text():
    reqs = load_requirements()
    assert len(reqs) >= 5
    for r in reqs:
        assert r.required_any, f"{r.id} 没有可接受表述"
        assert r.law_ref and r.law_text, f"{r.id} 缺法条——空法条等于放任 AI 自己编"
        assert r.remedy, f"{r.id} 缺整改方向"


def test_industry_filter(checker):
    """保健食品的必备声明不该套到游戏广告上。"""
    b = _bundle([_ocr("欢迎来到游戏世界", 1.0, 3.0)])
    ids = {f.requirement.id for f in checker.check_bundle(b, industry="game")}
    assert "health_food_disclaimer" not in ids
    assert "ad_identifiability" in ids, "通用条目应对所有行业适用"


# ── 四种状态 ──────────────────────────────────────────────────


def test_missing_when_absent(checker):
    b = _bundle([_ocr("三天见效 快速塑形", 1.0, 4.0)])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.MISSING
    assert f.is_risk
    assert f.evidence is None


def test_ok_when_prominent(checker):
    """时长够、字号够、不贴边 → 达标，不该报风险。"""
    b = _bundle([_ocr(DISCLAIMER, 20.0, 24.0, bbox=(0.30, 0.45, 0.40, 0.05))])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.OK
    assert not f.is_risk
    assert all(m.passed for m in f.measures)


def test_not_salient_too_brief(checker):
    """写了，但只闪了 0.4 秒 —— 这正是图 1 里那条免责声明。"""
    b = _bundle([_ocr(DISCLAIMER, 28.10, 28.50, bbox=(0.30, 0.45, 0.40, 0.05))])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")

    assert f.status is MandatoryStatus.NOT_SALIENT
    dur = next(m for m in f.measures if m.name == "持续时长")
    assert not dur.passed
    assert "0.40" in dur.measured, "报告要给出实测值，不能只说「太短」"
    assert "1.0" in dur.threshold, "同时要给出阈值，让人能判断差多少"


def test_not_salient_too_small(checker):
    b = _bundle([_ocr(DISCLAIMER, 20.0, 24.0, bbox=(0.30, 0.45, 0.40, 0.018))])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.NOT_SALIENT
    size = next(m for m in f.measures if m.name == "字号占画面高度")
    assert not size.passed
    assert "1.8%" in size.measured


def test_not_salient_hidden_in_corner(checker):
    """藏在右下角。"""
    b = _bundle([_ocr(DISCLAIMER, 20.0, 24.0, bbox=(0.75, 0.94, 0.22, 0.04))])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.NOT_SALIENT
    pos = next(m for m in f.measures if m.name == "画面位置")
    assert not pos.passed
    assert "距下边缘" in pos.measured, "要说清楚贴的是哪条边"


def test_spoken_only_is_flagged_separately(checker):
    """口播说了但画面没标——是否满足「显著标明」有解释空间，
    必须单列一类交人工判断，不能当成已达标，也不能当成完全缺失。"""
    b = _bundle([_asr(f"温馨提示，{DISCLAIMER}", 25.0, 28.0)])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.SPOKEN_ONLY
    assert f.is_risk
    assert f.evidence is not None and f.evidence.source == EvidenceSource.ASR


# ── 匹配鲁棒性（最关键的一组）─────────────────────────────────


def test_garbled_tiny_text_is_still_recognized(checker):
    """OCR 把小字识别错了，仍要判成「写了但不显著」，而不是「根本没写」。

    这是本模块最重要的一条：违规形态恰恰是「字太小」，
    而小字的识别错误率本就高。若精确匹配失败就报 MISSING，
    定性会从「排版问题」错成「完全遗漏」，整改方向也跟着错。
    """
    b = _bundle([_ocr("本品不能代誓药物", 28.1, 28.5, bbox=(0.75, 0.94, 0.20, 0.018))])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.NOT_SALIENT, (
        f"识别错字导致误判为 {f.status}；应当模糊匹配到并按显著性处理"
    )


def test_alternative_wording_accepted(checker):
    """法规与规章给出的等价表述都应认可。"""
    b = _bundle([_ocr("保健食品不是药物，不能代替药物治疗疾病", 20.0, 24.0)])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.OK


def test_short_marker_does_not_fuzzy_match(checker):
    """短标识不做模糊匹配，否则「广口告」之类的噪声会被当成合规标注。"""
    b = _bundle([_ocr("广口告", 1.0, 5.0, bbox=(0.3, 0.3, 0.3, 0.05))])
    f = _find(checker.check_bundle(b, industry=None), "ad_identifiability")
    assert f.status is MandatoryStatus.MISSING


# ── 广告可识别性：standalone 模式（防假通过）─────────────────

@pytest.mark.parametrize("text", [
    "广告合规审核系统",     # 产品名里含「广告」
    "广告法",               # 法条名
    "本广告仅供参考",       # 正文里提到广告
    "违法广告典型案例",
    "这是一条关于广告的说明文字",
])
def test_ad_marker_in_prose_is_not_a_marker(checker, text):
    """正文里出现「广告」二字不构成标识。

    《广告法》第十四条要的是「与其他非广告信息**相区别**」。
    放宽成子串包含会产生**假通过**——等于替客户签字说这条片子没问题，
    比误报危险得多。这组用例来自真实踩坑：一条广告合规产品的演示视频
    （画面里满是「广告合规」「广告法」）曾被判「已显著标明」。
    """
    b = _bundle([_ocr(text, 1.0, 6.0, bbox=(0.2, 0.3, 0.5, 0.05))])
    f = _find(checker.check_bundle(b, industry=None), "ad_identifiability")
    assert f.status is MandatoryStatus.MISSING, f"「{text}」被误认成了广告标识"


@pytest.mark.parametrize("text", [
    "广告",
    "【广告】",
    "[广告]",
    "广告 | 某某品牌",
    "某某品牌 · 推广",
    "赞助",
    "AD",
])
def test_real_ad_marker_is_recognized(checker, text):
    """真正的角标形态要认得出来，收紧不能收成谁都过不了。"""
    b = _bundle([_ocr(text, 1.0, 6.0, bbox=(0.80, 0.05, 0.12, 0.03))])
    f = _find(checker.check_bundle(b, industry=None), "ad_identifiability")
    assert f.status is MandatoryStatus.OK, f"真实角标「{text}」没被认出来"


def test_ad_marker_still_checked_for_salience(checker):
    """标识认出来了，仍要过显著性——一闪而过的角标不算标明。"""
    b = _bundle([_ocr("广告", 1.0, 1.3, bbox=(0.85, 0.04, 0.10, 0.03))])
    f = _find(checker.check_bundle(b, industry=None), "ad_identifiability")
    assert f.status is MandatoryStatus.NOT_SALIENT
    assert any(m.name == "持续时长" and not m.passed for m in f.measures)


def test_advisory_item_is_reported_but_not_counted(checker):
    """仅提示项：结论照常产出，但不计入风险数。

    这两件事必须分开 —— 当成「通过」会掩盖事实，
    计入风险数又会让每条片子固定挂一条、淹没真正的问题。
    """
    b = _bundle([_ocr("超值好物推荐", 1.0, 5.0)])
    f = _find(checker.check_bundle(b, industry=None), "ad_identifiability")

    assert f.requirement.advisory is True
    assert f.status is MandatoryStatus.MISSING
    assert f.is_risk is True, "核查确实没通过，不能粉饰成通过"
    assert f.counts_as_risk is False, "但不该计入风险数"


def test_advisory_payload_tells_llm_not_to_escalate(checker):
    """降级要传达给下游，否则大模型仍会把它写成风险项。"""
    b = _bundle([_ocr("超值好物推荐", 1.0, 5.0)])
    f = _find(checker.check_bundle(b, industry=None), "ad_identifiability")
    p = f.to_llm_payload()
    assert "仅提示" in p["处理层级"]
    assert "不得升级为风险项" in p["处理层级"]


def test_substantive_requirements_are_not_advisory(checker):
    """保健食品必备声明这类实体要求必须照常计入风险，别被降级波及。"""
    b = _bundle([_ocr("三天见效 快速塑形", 1.0, 4.0)])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.requirement.advisory is False
    assert f.counts_as_risk is True


def test_long_disclaimer_still_uses_contains_mode(checker):
    """收紧只针对短标识。长句免责声明仍走 contains，且保留模糊匹配容错。"""
    b = _bundle([_ocr("温馨提示：本品不能代替药物，请合理膳食", 20.0, 24.0)])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.OK, "长句免责声明不该被 standalone 规则波及"


def test_best_occurrence_wins(checker):
    """同一提示语出现两次，一次不合格一次合格 → 按合格的算。

    只要广告主正经展示过一次，要求即已满足。
    """
    b = _bundle([
        _ocr(DISCLAIMER, 5.0, 5.3, bbox=(0.80, 0.95, 0.18, 0.015), frame=1),   # 又短又小又贴边
        _ocr(DISCLAIMER, 20.0, 24.0, bbox=(0.30, 0.45, 0.40, 0.05), frame=60),  # 规规矩矩
    ])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    assert f.status is MandatoryStatus.OK
    assert f.evidence.frame_ids == [60]


# ── 输出契约 ──────────────────────────────────────────────────


def test_llm_payload_carries_law_and_wording_guard(checker):
    """喂给大模型的载荷必须带法条原文和措辞约束，且不含结论。"""
    b = _bundle([_ocr(DISCLAIMER, 28.1, 28.5, bbox=(0.75, 0.94, 0.20, 0.018))])
    f = _find(checker.check_bundle(b, "health_food"), "health_food_disclaimer")
    p = f.to_llm_payload()

    assert "第十八条" in p["法律依据"]
    assert p["法条原文"], "法条原文为空等于放任大模型自己编"
    assert "建议复核" in p["措辞要求"], "必须约束措辞，不得让模型写成「已构成违规」"
    assert len(p["显著性度量"]) == 3
    for key in p:
        assert key not in {"结论", "是否违规", "风险等级"}, "本层不下结论，定性交给涵摄推理"


def test_platform_label_note_surfaces(checker):
    """广告可识别性这条容易误报，必须把「平台侧已标注」的可能性带给下游。"""
    b = _bundle([_ocr("超值好物推荐", 1.0, 5.0)])
    f = _find(checker.check_bundle(b, industry=None), "ad_identifiability")
    assert "平台" in f.to_llm_payload()["特别说明"]
