"""涵摄推理测试。

这一层最危险的失败不是报错，是**结论与要件不一致** ——
要件里明明有一项不成立，结论却是「违规」。所以推导逻辑必须逐条锁死。
"""

import json
from pathlib import Path

import pytest

from app.reasoning.prompts import SYSTEM, build_user_prompt
from app.reasoning.report import (
    DISCLAIMER, Report, RiskLevel, finding_from_hit,
)
from app.reasoning.schema import (
    ElementAnswer, ElementResult, ElementSpec, RuleSpec,
    Subsumption, Verdict, load_rules,
)
from app.reasoning.subsume import MockLLMProvider, Subsumer, SubsumptionError


@pytest.fixture(scope="module")
def rules():
    return load_rules()[0]


def _spec(eid, needs_material=False, hint=""):
    return ElementSpec(id=eid, question=f"{eid}?", if_not=f"{eid} 不成立",
                       needs_material=needs_material, material_hint=hint)


def _rule(*specs):
    return RuleSpec(rule_id="T", name="测试规则", law_ref="《测试法》第一条",
                    elements=tuple(specs))


# ── 推导逻辑 ──────────────────────────────────────────────────


def test_all_yes_means_violation():
    rule = _rule(_spec("a"), _spec("b"))
    sub = Subsumption.derive(rule, [
        ElementResult(rule.elements[0], ElementAnswer.YES),
        ElementResult(rule.elements[1], ElementAnswer.YES),
    ])
    assert sub.verdict is Verdict.VIOLATION
    assert sub.blocking_element is None


def test_any_no_means_not_applicable():
    """任一必备要件不成立即不构成 —— 这是最干净的排除出口。"""
    rule = _rule(_spec("a"), _spec("b"))
    sub = Subsumption.derive(rule, [
        ElementResult(rule.elements[0], ElementAnswer.YES),
        ElementResult(rule.elements[1], ElementAnswer.NO, "属时间顺序表述"),
    ])
    assert sub.verdict is Verdict.NOT_APPLICABLE
    assert sub.blocking_element.spec.id == "b"
    assert not sub.is_risk


def test_uncertain_means_needs_facts_with_materials():
    rule = _rule(_spec("a"), _spec("b", needs_material=True, hint="第三方销量数据"))
    sub = Subsumption.derive(rule, [
        ElementResult(rule.elements[0], ElementAnswer.YES),
        ElementResult(rule.elements[1], ElementAnswer.UNCERTAIN, "素材未标注数据来源"),
    ])
    assert sub.verdict is Verdict.NEEDS_FACTS
    assert "第三方销量数据" in sub.required_materials
    assert sub.is_risk, "需核验意味着「尚不能排除」，不是「没问题」"


def test_no_takes_precedence_over_uncertain():
    """既有明确不成立、又有无法判断时，应走「不适用」而不是「待补材料」。

    反过来会让本可直接排除的情形白白挂上材料清单，
    平添运营的工作量，也稀释了真正需要补材料的条目。
    """
    rule = _rule(_spec("a", needs_material=True, hint="某材料"), _spec("b"))
    sub = Subsumption.derive(rule, [
        ElementResult(rule.elements[0], ElementAnswer.UNCERTAIN),
        ElementResult(rule.elements[1], ElementAnswer.NO),
    ])
    assert sub.verdict is Verdict.NOT_APPLICABLE
    assert sub.required_materials == []


# ── 真实规则 ──────────────────────────────────────────────────


def test_real_rules_have_elements_and_law_ref(rules):
    assert len(rules) >= 5
    for rid, spec in rules.items():
        assert spec.elements, f"{rid} 没有构成要件"
        assert spec.law_ref, f"{rid} 缺法律依据"
        for e in spec.elements:
            assert e.question.strip(), f"{rid}.{e.id} 问题为空"
            if e.needs_material:
                assert e.material_hint, f"{rid}.{e.id} 标了需材料却没说要什么材料"


def test_absolute_term_rule_encodes_all_four_exemptions(rules):
    """执法指南的四类可判断豁免必须都在要件里，漏一条就会误判。"""
    ids = {e.id for e in rules["ADLAW-009-03"].elements}
    assert ids == {"points_to_goods", "not_time_or_space_order",
                   "not_official_grade", "lacks_substantiation"}


def test_health_food_rule_protects_registered_functions(rules):
    """法定保健功能不得被判成疾病功效——这是保健食品这一路最容易误伤的地方。"""
    q = rules["ADLAW-018-01-02"].elements[1].question
    assert "增强免疫力" in q and "缓解体力疲劳" in q
    assert "不构成本项违规" in rules["ADLAW-018-01-02"].elements[1].if_not


# ── 提示词 ────────────────────────────────────────────────────


def test_prompt_carries_law_text_and_forbids_invention(rules):
    payload = {"命中词": "国家级", "上下文原文": "本品采用国家级配方",
               "法条原文": "广告不得使用「国家级」等用语", "判定要点": "法条明文列举"}
    p = build_user_prompt(rules["ADLAW-009-03"], payload)

    assert "广告不得使用「国家级」等用语" in p
    assert "不得自行补充" in p
    assert "本品采用国家级配方" in p
    assert "不得引用、补充或生成任何未提供的法条" in SYSTEM


def test_prompt_does_not_ask_for_verdict(rules):
    """不能给模型「是否违规」这个问题——定性是代码的活。"""
    p = build_user_prompt(rules["ADLAW-009-03"], {"命中词": "国家级"})
    assert "是否违规" not in p
    assert "不要给出「是否违规」的整体结论" in SYSTEM


def test_prompt_separates_facts_from_rules(rules):
    """事实与规则必须分区。混排时模型会把法条里的例词当成素材里出现的词。"""
    p = build_user_prompt(rules["ADLAW-009-03"], {"命中词": "最佳"})
    assert p.index("待审事实") < p.index("适用规则")


def test_uncertain_is_declared_legitimate():
    assert "uncertain 是正当答案" in SYSTEM


# ── LLM 解析 ──────────────────────────────────────────────────


def test_missing_element_defaults_to_uncertain_not_yes(rules):
    """模型漏答一项时按「无法判断」处理。

    默认成立等于把模型的沉默当成肯定答复，会凭空造出违规结论。
    """
    class Partial(MockLLMProvider):
        def complete(self, system, user):
            return json.dumps({"elements": [
                {"id": "points_to_goods", "answer": "yes", "reason": "指向商品"}]})

    sub = Subsumer(llm=Partial()).subsume("ADLAW-009-03", {"命中词": "国家级"})
    assert sub.verdict is Verdict.NEEDS_FACTS
    answered = {r.spec.id: r.answer for r in sub.results}
    assert answered["not_time_or_space_order"] is ElementAnswer.UNCERTAIN


def test_invalid_answer_value_degrades_to_uncertain(rules):
    class Bad(MockLLMProvider):
        def complete(self, system, user):
            return json.dumps({"elements": [
                {"id": "points_to_goods", "answer": "大概是吧", "reason": ""}]})

    sub = Subsumer(llm=Bad()).subsume("ADLAW-009-03", {"命中词": "国家级"})
    assert all(r.answer is not ElementAnswer.YES for r in sub.results)


def test_non_json_response_raises(rules):
    class Chatty(MockLLMProvider):
        def complete(self, system, user):
            return "我认为这条广告可能有问题，建议修改。"

    with pytest.raises(SubsumptionError, match="找不到 JSON"):
        Subsumer(llm=Chatty()).subsume("ADLAW-009-03", {"命中词": "国家级"})


def test_mock_defaults_to_uncertain():
    """不会推理的替身，唯一诚实的表态就是「判断不了」。"""
    sub = Subsumer(llm=MockLLMProvider()).subsume("ADLAW-017", {"命中词": "治疗"})
    assert sub.verdict is Verdict.NEEDS_FACTS


def test_unknown_rule_returns_none():
    assert Subsumer(llm=MockLLMProvider()).subsume("NO-SUCH-RULE", {}) is None


def test_rule_alias_resolves():
    s = Subsumer(llm=MockLLMProvider())
    assert s.resolve_rule("ADLAW-018").rule_id == "ADLAW-018-01-02"


# ── 报告组装 ──────────────────────────────────────────────────


class _Entry:
    law_ref = "《广告法》第九条第（三）项"
    risk = "high"


class _Hit:
    matched_text = "国家级"
    context = "本品采用国家级配方"
    t_start, t_end = 3.88, 4.54
    source = "asr"
    frame_ids: list[int] = []
    entry = _Entry()


def test_finding_without_subsumption_does_not_assert_violation():
    """没做涵摄就不能下定性结论。粗筛只是「找到嫌疑」，
    把嫌疑写成风险是这个产品最不能犯的错。"""
    f = finding_from_hit(_Hit(), None)
    assert f.level is RiskLevel.ADVISORY
    assert f.counts_as_risk is False
    assert "未作涵摄推理" in f.qualification


def test_finding_needs_facts_lists_materials():
    rule = _rule(_spec("a", needs_material=True, hint="第三方销量数据与统计口径"))
    sub = Subsumption.derive(rule, [ElementResult(rule.elements[0], ElementAnswer.UNCERTAIN)])
    f = finding_from_hit(_Hit(), sub)

    assert f.level is RiskLevel.MEDIUM
    assert "第三方销量数据与统计口径" in f.required_materials
    assert f.element_trace, "要件判断过程必须留痕，法务要追问「为什么是这个结论」"


def test_finding_not_applicable_is_not_counted():
    rule = _rule(_spec("a"))
    sub = Subsumption.derive(rule, [ElementResult(rule.elements[0], ElementAnswer.NO, "属时间顺序")])
    f = finding_from_hit(_Hit(), sub)
    assert f.counts_as_risk is False
    assert f.category == "已排除"


def test_report_level_takes_the_most_severe_risk():
    rule = _rule(_spec("a"))
    violation = Subsumption.derive(rule, [ElementResult(rule.elements[0], ElementAnswer.YES)])
    excluded = Subsumption.derive(rule, [ElementResult(rule.elements[0], ElementAnswer.NO)])

    rep = Report(review_id="r", video_path="t.mp4", duration=30.0, findings=[
        finding_from_hit(_Hit(), excluded),
        finding_from_hit(_Hit(), violation),
    ])
    assert rep.level is RiskLevel.HIGH
    assert len(rep.risks) == 1 and len(rep.advisories) == 1


def test_report_always_carries_disclaimer():
    rep = Report(review_id="r", video_path="t.mp4", duration=30.0)
    assert rep.to_dict()["免责声明"] == DISCLAIMER
    assert "不构成法律意见" in DISCLAIMER


def test_every_finding_has_all_six_segments():
    rule = _rule(_spec("a"))
    sub = Subsumption.derive(rule, [ElementResult(rule.elements[0], ElementAnswer.YES)])
    d = finding_from_hit(_Hit(), sub).to_dict()
    for seg in ("风险定性", "风险表达", "违规类型", "法律依据", "修改建议", "风险定级"):
        assert d.get(seg), f"六段式缺了「{seg}」"


# ── 类案检索 ──────────────────────────────────────────────────

from app.reasoning.cases import Case, CaseLibrary, ScoredCase  # noqa: E402
from app.reasoning.report import _cases_to_dicts  # noqa: E402


def _case(cid, **kw):
    base = dict(
        case_id=cid, title=f"案例{cid}", industry="保健食品", sector="health_food",
        penalty_authority="某市市场监管局", penalty_amount=450000,
        illegal_claims=("治疗糖尿病",), legal_basis=("《广告法》",),
        mapped_rule_ids=("ADLAW-017",), keywords=("疾病功效",),
        vector_text="宣称可治疗糖尿病", regulatory_logic="认定涉及疾病治疗功能",
        source_url="https://example.gov.cn/x", review_status="approved",
    )
    base.update(kw)
    return Case(**base)


def _lib(*cases):
    return CaseLibrary(cases={c.case_id: c for c in cases})


def test_linked_cases_outrank_similarity():
    """词库直接关联的案例必须排在相似度召回之前。

    那是挖词时记录的「这个词就是在这些案子里被罚的」，
    比任何文本相似度都准。
    """
    lib = _lib(_case("linked", illegal_claims=(), mapped_rule_ids=(), vector_text=""),
               _case("similar"))
    got = lib.retrieve(term="治疗", rule_id="ADLAW-017", industry="health_food",
                       linked_case_ids=("linked",))
    assert got[0].case.case_id == "linked"
    assert "词库直接关联" in got[0].reason


def test_unverified_case_is_marked():
    """未核验的候选案例不能被当成既定判例呈现。"""
    lib = _lib(_case("c1", review_status="candidate"))
    got = lib.retrieve(term="治疗", rule_id="ADLAW-017")
    assert not got[0].case.verified
    assert "待核验" in got[0].case.citation()
    assert "待核验" in _cases_to_dicts(got)[0]["核验状态"]


def test_case_without_source_url_is_not_verified():
    """无出处即不可引用——法务要能回溯原文。"""
    assert not _case("c1", source_url="", review_status="approved").verified


def test_report_marks_cases_as_reference_only():
    """类案进报告必须带「不构成事实认定」的说明。

    别的公司被罚过，不构成本案的事实认定。少了这句，
    报告读起来就像在说「你和他们一样违规」。
    """
    rule = _rule(_spec("a"))
    sub = Subsumption.derive(rule, [ElementResult(rule.elements[0], ElementAnswer.YES)])
    lib = _lib(_case("c1"))
    d = finding_from_hit(_Hit(), sub, lib.retrieve(term="治疗", rule_id="ADLAW-017")).to_dict()

    assert d["相似监管实践"]
    assert "不构成对本素材的事实认定" in d["类案说明"]
    assert d["相似监管实践"][0]["原文出处"].startswith("https://")


def test_retrieval_returns_empty_without_matches():
    lib = _lib(_case("c1", mapped_rule_ids=(), illegal_claims=(), vector_text="", keywords=()))
    assert lib.retrieve(term="完全无关的词", rule_id="NO-RULE", industry="game") == []


def test_missing_library_degrades_gracefully():
    """refs/ 没解压时不能崩，检索返回空即可。"""
    lib = CaseLibrary.load(roots=(Path("/no/such/dir"),))
    assert not lib.available
    assert lib.retrieve(term="治疗") == []
