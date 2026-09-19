"""抓取策略与质量门禁测试。

这两层编码的是**决策**而非实现：robots 拿不到时是放行还是拒绝、
脱敏判错时往哪边错、金额核不上是拒收还是清空。
每一条都可能在赶进度时被人「顺手改一下」，所以逐条锁死。
"""

import inspect
from datetime import date

import pytest

from app.crawler.policy import (
    UA, RateLimiter, RobotsDenied, RobotsGate,
    desensitize_party, is_organization, mask_person_name,
)
from app.crawler.quality import (
    DedupIndex, Severity, amount_renderings, extract_doc_number,
    fingerprint, looks_like_keyword_soup, validate_case, verify_amount,
)

ALLOW_ALL = "User-agent: *\nAllow: /\n"
DENY_ALL = "User-agent: *\nDisallow: /\n"


def _gate(text: str | None):
    def fetcher(url):
        if text is None:
            raise ConnectionError("模拟网络故障")
        return text
    return RobotsGate(fetcher=fetcher)


# ══════════════════════════════════════════════════════════════
#  robots 门禁
# ══════════════════════════════════════════════════════════════


def test_robots_allows_permitted_url():
    _gate(ALLOW_ALL).check("https://example.gov.cn/list")  # 不抛即通过


def test_robots_denies_disallowed_url():
    with pytest.raises(RobotsDenied, match="不允许抓取"):
        _gate(DENY_ALL).check("https://example.gov.cn/list")


def test_network_failure_defaults_to_deny():
    """网络故障 / 5xx —— 状态未知，按禁止处理。

    此时继续抓既失礼，也让我们说不清自己合不合规。
    """
    with pytest.raises(RobotsDenied, match="按禁止处理"):
        _gate(None).check("https://example.gov.cn/list")


def test_absent_robots_is_allowed_per_rfc():
    """站点明确回 4xx = 「本站没有限制」的肯定答复，不是失败。

    RFC 9309 §2.3.1.3：服务器返回 4xx 时，爬虫可访问全部资源。
    早先把「明确没有」和「不知道」合并成「拿不到就拒绝」，
    结果 samr.gov.cn 这种没有 robots.txt 的站点被自己的门禁挡在外面 ——
    实测踩到的。
    """
    def missing(url):
        raise FileNotFoundError("HTTP 404")
    RobotsGate(fetcher=missing).check("https://example.gov.cn/list")  # 不抛即通过


def test_html_error_page_is_not_parsed_as_robots():
    """HTML 错误页当 robots 解析会解出「允许一切」—— 静默失效，必须挡住。

    实测 creditchina.gov.cn：它的 404 页是 HTML，被 robots 解析器吃下去后
    找不到任何 Disallow，于是判成放行。任何用 HTML 错误页代替标准 404 的站点
    都能让门禁形同虚设。
    """
    html_404 = "<!DOCTYPE html><html><head><title>404</title></head><body>没找到</body></html>"
    with pytest.raises(RobotsDenied, match="按禁止处理"):
        _gate(html_404).check("https://example.gov.cn/list")


def test_absent_robots_still_uses_default_crawl_delay():
    """没有 robots 不等于可以不限速 —— 礼貌那一级仍然生效。"""
    def missing(url):
        raise FileNotFoundError("HTTP 404")
    assert RobotsGate(fetcher=missing).crawl_delay("https://x.gov.cn/a", default=3.0) == 3.0


def test_robots_gate_has_no_bypass_switch():
    """check() 不能有 force / skip / ignore 之类的参数。

    留了绕过开关，就一定会有人在赶进度时打开，然后它会永远开着。
    真需要抓 robots 禁止的页面，那是要人去跟对方沟通的事。
    """
    params = set(inspect.signature(RobotsGate.check).parameters) - {"self", "url"}
    assert not params, f"robots 门禁多出了可能被用来绕过的参数：{params}"


def test_robots_respects_declared_crawl_delay():
    """对方要求更慢就听对方的，不能只用我们自己的默认值。"""
    gate = _gate("User-agent: *\nAllow: /\nCrawl-delay: 10\n")
    assert gate.crawl_delay("https://example.gov.cn/x", default=3.0) == 10.0


def test_user_agent_identifies_us():
    """不伪装成浏览器。"""
    assert "Mozilla" not in UA
    assert "AdsureCaseBot" in UA


def test_user_agent_must_be_ascii():
    """HTTP 头按 latin-1 编码，UA 里放中文会让每次请求在发出前就抛异常。

    这是真实抓取时踩出来的：单元测试注入假客户端、从不真正发送 header，
    所以第一次连真实站点才暴露。这条测试就是那次的回归防护。
    """
    assert UA.isascii(), f"UA 含非 ASCII 字符，HTTP 头发不出去：{UA!r}"
    UA.encode("latin-1")  # 抛异常即失败


def test_user_agent_does_not_leak_personal_email_by_default():
    """联系方式是好礼仪，但 UA 会广播给每个被抓的站点。

    公开谁的邮箱是本人的选择，不该由代码替他决定 ——
    需要时通过 CRAWLER_CONTACT 环境变量显式提供。
    """
    assert "@" not in UA


# ══════════════════════════════════════════════════════════════
#  两级限速
# ══════════════════════════════════════════════════════════════


class _Clock:
    def __init__(self):
        self.t = 0.0
    def now(self):
        return self.t
    def sleep(self, s):
        self.t += s
    def advance(self, s):
        self.t += s


def _limiter(cases_per_hour=50, interval=3.0):
    clk = _Clock()
    return RateLimiter(cases_per_hour=cases_per_hour, min_request_interval=interval,
                       _sleep=clk.sleep, _now=clk.now), clk


def test_request_interval_enforced_per_host():
    rl, clk = _limiter(interval=3.0)
    assert rl.before_request("a.gov.cn") == 0.0          # 首次不等
    assert rl.before_request("a.gov.cn") == pytest.approx(3.0)
    # 不同站点互不影响 —— 礼貌是对每个站点各自而言的
    assert rl.before_request("b.gov.cn") == 0.0


def test_case_quota_is_fifty_per_hour():
    rl, clk = _limiter(cases_per_hour=50)
    assert rl.remaining_quota() == 50
    for _ in range(50):
        assert rl.try_consume_case() is True
    assert rl.remaining_quota() == 0


def test_quota_exhausted_returns_false_instead_of_blocking():
    """配额用尽应当**停下来收工**，而不是挂在那里等一小时。

    长时间挂起的抓取任务没人看得住，也回答不了「现在跑到哪了」。
    """
    rl, clk = _limiter(cases_per_hour=2)
    rl.try_consume_case(); rl.try_consume_case()
    before = clk.t
    assert rl.try_consume_case() is False
    assert clk.t == before, "配额耗尽时不应发生任何等待"


def test_quota_recovers_after_an_hour():
    rl, clk = _limiter(cases_per_hour=2)
    rl.try_consume_case(); rl.try_consume_case()
    clk.advance(3601)
    assert rl.remaining_quota() == 2


def test_case_quota_persists_across_process_instances(tmp_path):
    """Restarting the crawler must not reset the hourly review-capacity gate."""
    clock = _Clock()
    state = tmp_path / "quota.json"
    first = RateLimiter(cases_per_hour=2, min_request_interval=0.0,
                        quota_state_path=state, _wall_now=clock.now)
    assert first.try_consume_case() is True
    assert first.try_consume_case() is True

    restarted = RateLimiter(cases_per_hour=2, min_request_interval=0.0,
                            quota_state_path=state, _wall_now=clock.now)
    assert restarted.remaining_quota() == 0
    assert restarted.try_consume_case() is False

    clock.advance(3601)
    assert restarted.remaining_quota() == 2


def test_corrupt_persistent_quota_fails_closed(tmp_path):
    state = tmp_path / "quota.json"
    state.write_text("not json", encoding="utf-8")
    limiter = RateLimiter(quota_state_path=state)
    with pytest.raises(RuntimeError, match="配额状态文件不可读"):
        limiter.remaining_quota()


def test_two_limiters_are_independent_knobs():
    """请求间隔（礼貌）与案例配额（产能）是两回事，调一个不能影响另一个。"""
    rl, _ = _limiter(cases_per_hour=1, interval=0.0)
    assert rl.min_request_interval == 0.0
    assert rl.cases_per_hour == 1


# ══════════════════════════════════════════════════════════════
#  姓名脱敏
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("name", [
    "上海某某生物科技有限公司", "北京健康管理中心", "杭州某某商贸有限公司",
    "个体工商户张记药房", "某某集团股份有限公司",
])
def test_organizations_are_kept(name):
    assert desensitize_party(name) == name
    assert is_organization(name)


@pytest.mark.parametrize("name,expected", [
    ("张三", "张*"),
    ("李小明", "李**"),
    ("欧阳修文", "欧阳**"),
    ("司马相如", "司马**"),
])
def test_person_names_are_masked(name, expected):
    assert desensitize_party(name) == expected


def test_unclear_names_default_to_masking():
    """判定必然有误差，**误差方向必须选对**。

    把企业名误判成人名 → 报告里少个名字，无伤大雅
    把人名误判成企业名 → 真实姓名进了 RAG、进了给客户的报告
    所以拿不准一律掩码。
    """
    assert desensitize_party("赵四") == "赵*"
    assert "*" in desensitize_party("某甲")


def test_mask_keeps_surname_for_traceability():
    """保留姓氏，让人工复核时还能与原文对上。"""
    assert mask_person_name("王五").startswith("王")


# ══════════════════════════════════════════════════════════════
#  金额核对
# ══════════════════════════════════════════════════════════════


@pytest.mark.parametrize("text", [
    "罚款600000元", "罚款60万元", "处以600,000元罚款", "罚款 60万",
])
def test_amount_verified_across_renderings(text):
    """决定书通常写「六十万元」或「60万元」，只搜 600000 会搜不到。

    只搜一种写法会把正确的抽取结果误判成幻觉 —— 那比不校验还糟。
    """
    assert verify_amount(600000, text) is True


def test_amount_not_in_text_fails_verification():
    assert verify_amount(600000, "罚款五万元整") is False


def test_amount_renderings_cover_common_forms():
    r = amount_renderings(600000)
    assert "600000" in r and "60万元" in r and "600,000" in r


# ══════════════════════════════════════════════════════════════
#  质量门禁
# ══════════════════════════════════════════════════════════════


def _case(**kw):
    base = {
        "case_id": "test_001",
        "source_url": "https://example.gov.cn/case/1",
        "raw_text_path": "data/raw_text/test_001.json",
        "party_name": "某某公司",
        "penalty_authority": "上海市市场监督管理局",
        "publish_date": "2025-06-01",
        "penalty_amount": 600000,
        "vector_text": "经营者在短视频广告中宣称产品可以治疗糖尿病，监管机关认定其构成疾病治疗功效宣传。",
        "review_status": "pending_review",
    }
    base.update(kw)
    return base


RAW = "……当事人发布广告宣称可治疗糖尿病，罚款60万元……"


def test_missing_source_url_is_rejected():
    """没有出处的案例直接拒收 —— 它在报告里根本不能引用。"""
    r = validate_case(_case(source_url=""), RAW)
    assert r.rejected
    assert any(i.field == "source_url" and i.severity is Severity.REJECT for i in r.issues)


@pytest.mark.parametrize("title", [
    "案情回顾：精心编造的“某大型科技公司前首席女技术黑客”人设",
    "联合执法：多部门协同作战",
    "温馨提醒：共建清朗网络空间",
    "下一步工作安排",
])
def test_article_headings_are_rejected_not_landed(title):
    """总局有些通报是叙事式新闻稿，小节标题不是案子名。

    实测入库 111 条里混进 4 条这种。它们进了 RAG 会被当成真实案例检索出来 ——
    比少 4 条案例糟得多。
    """
    r = validate_case(_case(segment_title=title), RAW)
    assert r.rejected


def test_case_without_party_or_authority_is_rejected():
    """两个都缺，连「谁被谁罚了」都答不出 —— 与 source_url 缺失同理。"""
    r = validate_case(_case(party_name="", penalty_authority=""), RAW)
    assert r.rejected


@pytest.mark.parametrize("missing", ["party_name", "penalty_authority"])
def test_missing_only_one_of_them_is_not_rejected(missing):
    """单独缺一个是抽取失败，案例仍可用 —— 不要因为抽漏而丢掉真案例。"""
    assert not validate_case(_case(**{missing: ""}), RAW).rejected


def test_missing_raw_text_is_rejected():
    r = validate_case(_case(), raw_text="")
    assert r.rejected


def test_unverifiable_amount_is_cleared_not_rejected():
    """金额核不上就清掉，案例本身仍有价值。

    报告里引用一个不存在的罚款金额，比不引用糟糕得多。
    """
    r = validate_case(_case(penalty_amount=999999), RAW)
    assert not r.rejected
    assert r.case["penalty_amount"] is None
    assert any(i.field == "penalty_amount" and i.severity is Severity.REPAIR for i in r.issues)


def test_verifiable_amount_survives():
    r = validate_case(_case(), RAW)
    assert r.case["penalty_amount"] == 600000


def test_inferred_article_is_flagged_for_human_review():
    """隔离了还不够 —— 复核的人得看见它，才能决定要不要去查决定书原件。"""
    c = _case(legal_basis=["《中华人民共和国广告法》"],
              legal_basis_inferred=["《中华人民共和国广告法》第十七条"])
    r = validate_case(c, "依据《中华人民共和国广告法》有关规定，罚款10万元。")
    assert not r.rejected
    assert "legal_basis_inferred" in r.flags


def test_unknown_rule_id_is_flagged_not_rejected():
    """规则目录里没有，多半是目录缺条（如已知缺 ADLAW-008），不是案例的错。"""
    r = validate_case(_case(mapped_rule_ids=["ADLAW-008"]), RAW,
                      known_rule_ids={"ADLAW-017", "ADLAW-028"})
    assert not r.rejected
    assert any(i.field == "mapped_rule_ids" and i.severity is Severity.FLAG for i in r.issues)


def test_future_date_is_flagged():
    r = validate_case(_case(publish_date="2099-01-01"), RAW, today=date(2026, 9, 3))
    assert any(i.field == "publish_date" for i in r.issues)
    assert not r.rejected


def test_keyword_soup_vector_text_is_cleared():
    r = validate_case(_case(vector_text="保健食品、虚假宣传、疾病治疗、罚款、市监局、广告法"), RAW)
    assert r.case["vector_text"] == ""
    assert any(i.field == "vector_text" for i in r.issues)


def test_natural_language_vector_text_survives():
    r = validate_case(_case(), RAW)
    assert r.case["vector_text"]


@pytest.mark.parametrize("text,expected", [
    ("保健食品、虚假宣传、疾病治疗、罚款、市监局、广告法、处罚", True),
    ("太短", True),
    ("经营者在短视频广告中宣称其保健食品可以治疗糖尿病，监管机关认定构成疾病治疗功效宣传。", False),
])
def test_keyword_soup_detection(text, expected):
    assert looks_like_keyword_soup(text) is expected


def test_crawled_case_can_never_self_approve():
    """抓取产出不得自带 approved。两级入库的意义就是人必须在环。"""
    r = validate_case(_case(review_status="approved"), RAW)
    assert r.case["review_status"] == "pending_review"
    assert any(i.field == "review_status" for i in r.issues)


def test_validate_does_not_mutate_input():
    original = _case(penalty_amount=999999)
    snapshot = dict(original)
    validate_case(original, RAW)
    assert original == snapshot, "校验不应就地改写调用方的数据"


# ══════════════════════════════════════════════════════════════
#  去重
# ══════════════════════════════════════════════════════════════


def test_doc_number_extracted_from_raw_text():
    txt = "上海市市场监督管理局作出沪市监徐处〔2025〕012号行政处罚决定"
    assert "2025" in (extract_doc_number(txt) or "")


def test_fingerprint_prefers_doc_number():
    """文号是最可靠的指纹：同一决定书在不同网站转载，文号一样。"""
    txt = "……沪市监徐处〔2025〕012号……"
    fp, basis = fingerprint(_case(), txt)
    assert basis == "文号"
    # 换个 case_id、换个源，只要文号相同就是同一案
    fp2, _ = fingerprint(_case(case_id="other", source_url="https://b.gov.cn/x"), txt)
    assert fp == fp2


def test_fingerprint_falls_back_to_authority_party_date():
    fp, basis = fingerprint(_case(), raw_text="没有文号的正文")
    assert basis == "机关+当事人+日期"


def test_duplicate_across_sources_is_merged_not_dropped():
    """多源印证是可信度信号，所以记录而不是丢弃。"""
    idx = DedupIndex()
    txt = "……沪市监徐处〔2025〕012号……"
    first = _case(source_url="https://a.gov.cn/1")
    dup, existing, _ = idx.check(first, txt)
    assert dup is False

    second = _case(case_id="other", source_url="https://b.gov.cn/2")
    dup, existing, basis = idx.check(second, txt)
    assert dup is True and existing is first and basis == "文号"

    merged = idx.merge_source(existing, second)
    assert "https://b.gov.cn/2" in merged["also_seen_at"]
    assert merged["source_url"] == "https://a.gov.cn/1", "主记录不被覆盖"


# ══════════════════════════════════════════════════════════════
#  抽取：引用核对（反幻觉）
# ══════════════════════════════════════════════════════════════

from app.crawler.extract import CRITICAL_FIELDS, Extractor, to_case  # noqa: E402
from app.crawler.fetch import Fetcher, html_to_text  # noqa: E402

DOC = "上海市市场监督管理局：当事人某某公司发布广告宣称可治疗糖尿病，罚款60万元。"


class _LLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
    def complete(self, system, user):
        self.calls += 1
        import json as _j
        return _j.dumps(self.payload, ensure_ascii=False)


def test_field_with_verifiable_quote_is_kept():
    llm = _LLM({"fields": {
        "penalty_authority": {"value": "上海市市场监督管理局", "quote": "上海市市场监督管理局"},
    }})
    r = Extractor(llm).extract(DOC)
    assert r.fields["penalty_authority"] == "上海市市场监督管理局"
    assert not r.dropped


def test_fabricated_quote_causes_field_to_be_dropped():
    """引用在原文里搜不到 = 模型编的 = 该字段作废。

    这比「让模型别编」有效得多：后者是请求，前者是校验，
    而且校验只需要字符串匹配，不需要另一个模型。
    """
    llm = _LLM({"fields": {
        "penalty_amount": {"value": 5000000, "quote": "罚款五百万元"},  # 原文里没有
    }})
    r = Extractor(llm).extract(DOC)
    assert "penalty_amount" not in r.fields
    assert "penalty_amount" in r.dropped
    assert r.hallucination_rate == 1.0


def test_quote_matching_ignores_whitespace():
    """原文换行/空格不该导致误判为幻觉。"""
    llm = _LLM({"fields": {
        "penalty_authority": {"value": "上海市市场监督管理局", "quote": "上海市 市场监督管理局"},
    }})
    assert "penalty_authority" in Extractor(llm).extract(DOC).fields


def test_narrative_field_may_paraphrase_but_needs_a_source_paragraph():
    """叙述类字段是概括，不要求逐字命中；但一个字都引不出来，
    说明模型压根没在读原文。"""
    llm = _LLM({"fields": {
        "vector_text": {"value": "经营者宣称保健食品可治疗糖尿病，被认定疾病功效宣传。",
                        "quote": "宣称可治疗糖尿病"},
        "facts_summary": {"value": "某公司虚假宣传", "quote": None},
    }})
    r = Extractor(llm).extract(DOC)
    assert "vector_text" in r.fields
    assert "facts_summary" in r.dropped


def test_null_values_are_skipped_not_dropped():
    """原文没有就填 null 是**正确行为**，不该记成幻觉。"""
    llm = _LLM({"fields": {
        "doc_number": {"value": None, "quote": None},
        "penalty_authority": {"value": "上海市市场监督管理局", "quote": "上海市市场监督管理局"},
    }})
    r = Extractor(llm).extract(DOC)
    assert "doc_number" not in r.fields and "doc_number" not in r.dropped


def test_critical_fields_are_declared():
    """三个高危字段编造的后果最严重，必须显式声明并强制核对。"""
    assert set(CRITICAL_FIELDS) == {"penalty_amount", "penalty_authority", "legal_basis"}


def test_to_case_desensitizes_party_name_early():
    """脱敏要尽早，别让原始姓名流到下游。"""
    llm = _LLM({"fields": {"party_name": {"value": "张三", "quote": "张三"}}})
    r = Extractor(llm).extract("当事人张三发布广告")
    c = to_case(r, "c1", "https://x.gov.cn/1", "data/raw_text/c1.json")
    assert c["party_name"] == "张*"
    assert c["review_status"] == "pending_review"


def test_to_case_records_dropped_fields():
    """幻觉记录要留痕，方便日后评估模型可靠性。"""
    llm = _LLM({"fields": {"penalty_amount": {"value": 999, "quote": "不存在的引用"}}})
    r = Extractor(llm).extract(DOC)
    c = to_case(r, "c1", "https://x.gov.cn/1", "p.json")
    assert "penalty_amount" in c["extraction_dropped"]


# ══════════════════════════════════════════════════════════════
#  抓取
# ══════════════════════════════════════════════════════════════


def test_robots_is_checked_before_any_request():
    """顺序是刻意的：先查 robots 再发请求。

    反过来等于已经打扰了对方，才回头去问准不准。
    """
    calls = []
    def client(url):
        calls.append(url)
        return 200, "<html>ok</html>"

    f = Fetcher(gate=_gate(DENY_ALL), limiter=_limiter()[0], client=client)
    with pytest.raises(RobotsDenied):
        f.fetch("https://example.gov.cn/case/1")
    assert calls == [], "robots 拒绝后不应发出任何请求"


def test_fetch_records_sha256_for_provenance():
    """存证：站点日后改版或删文时，能证明我们当时看到的就是这个。"""
    f = Fetcher(gate=_gate(ALLOW_ALL), limiter=_limiter()[0],
                client=lambda u: (200, "<html><body>正文</body></html>"))
    r = f.fetch("https://example.gov.cn/case/1")
    assert r.ok and len(r.sha256) == 64
    assert r.fetched_at and r.ua == UA


def test_html_to_text_strips_scripts_and_tags():
    t = html_to_text("<html><script>var x=1;</script><p>罚款60万元</p></html>")
    assert "罚款60万元" in t and "var x" not in t


def test_persist_never_overwrites_existing_raw_data(tmp_path):
    """原始数据只增不覆盖 —— 覆盖了就找不回来（AGENTS.md 红线）。"""
    f = Fetcher(gate=_gate(ALLOW_ALL), limiter=_limiter()[0],
                client=lambda u: (200, "<p>第一次</p>"))
    r1 = f.fetch("https://example.gov.cn/1")
    p1 = Fetcher.persist(r1, "case_x", tmp_path / "data")

    f2 = Fetcher(gate=_gate(ALLOW_ALL), limiter=_limiter()[0],
                 client=lambda u: (200, "<p>第二次</p>"))
    r2 = f2.fetch("https://example.gov.cn/1")
    p2 = Fetcher.persist(r2, "case_x", tmp_path / "data")

    assert p1["raw_text_path"] != p2["raw_text_path"]
    first = (tmp_path / "data" / "raw_html" / "case_x.html").read_text(encoding="utf-8")
    assert "第一次" in first, "首次抓到的原始数据被覆盖了"


# ══════════════════════════════════════════════════════════════
#  编排管道
# ══════════════════════════════════════════════════════════════

from app.crawler.pipeline import CrawlPipeline, Outcome  # noqa: E402

GOOD = {"fields": {
    "penalty_authority": {"value": "上海市市场监督管理局", "quote": "上海市市场监督管理局"},
    "party_name": {"value": "某某公司", "quote": "某某公司"},
    "penalty_amount": {"value": 600000, "quote": "60万元"},
    "publish_date": {"value": "2025-06-01", "quote": "2025-06-01"},
    "vector_text": {"value": "经营者在广告中宣称保健食品可治疗糖尿病，被监管机关认定为疾病治疗功效宣传。",
                    "quote": "宣称可治疗糖尿病"},
}}

PAGE = ("<html><body>上海市市场监督管理局 2025-06-01：当事人某某公司发布广告，"
        "宣称可治疗糖尿病，罚款60万元。</body></html>")


def _pipeline(tmp_path, payload=GOOD, page=PAGE, cases_per_hour=50):
    rl, _ = _limiter(cases_per_hour=cases_per_hour, interval=0.0)
    fetcher = Fetcher(gate=_gate(ALLOW_ALL), limiter=rl, client=lambda u: (200, page))
    return CrawlPipeline(llm=_LLM(payload), data_dir=tmp_path / "data",
                         fetcher=fetcher, limiter=rl)


def test_landed_case_goes_to_candidates_never_structured(tmp_path):
    """管道终点永远是候选库。两级入库的意义就在于人必须在环。"""
    p = _pipeline(tmp_path)
    (r,) = p.process("https://x.gov.cn/1", "c1")   # 单案例页返回一条
    assert r.outcome == Outcome.LANDED

    assert (tmp_path / "data" / "structured_candidates" / "c1.json").exists()
    assert not (tmp_path / "data" / "structured").exists(), "绝不允许自动写入正式库"

    import json as _j
    saved = _j.loads((tmp_path / "data" / "structured_candidates" / "c1.json").read_text("utf-8"))
    assert saved["review_status"] == "pending_review"
    assert saved["content_sha256"] and saved["source_url"]


def test_quota_exhaustion_stops_the_run(tmp_path):
    """配额用尽就收工，不挂在那里等一小时。

    每个 URL 给不同的当事人 —— 否则会被去重判成重复案例，
    测到的就不是配额逻辑了。
    """
    rl, _ = _limiter(cases_per_hour=2, interval=0.0)
    fetcher = Fetcher(
        gate=_gate(ALLOW_ALL), limiter=rl,
        client=lambda u: (200, f"<html><body>上海市市场监督管理局 2025-06-0{u[-1]}："
                               f"当事人第{u[-1]}公司发布广告，罚款60万元。</body></html>"),
    )

    class _PerUrlLLM:
        def complete(self, system, user):
            import json as _j, re as _re
            n = (_re.search(r"当事人第(\d)公司", user) or [None, "0"])[1]
            return _j.dumps({"fields": {
                "penalty_authority": {"value": "上海市市场监督管理局", "quote": "上海市市场监督管理局"},
                "party_name": {"value": f"第{n}公司", "quote": f"第{n}公司"},
                "publish_date": {"value": f"2025-06-0{n}", "quote": f"2025-06-0{n}"},
                "vector_text": {"value": "经营者在广告中作出不实宣称，监管机关认定构成虚假广告并处以罚款。",
                                "quote": "发布广告"},
            }}, ensure_ascii=False)

    p = CrawlPipeline(llm=_PerUrlLLM(), data_dir=tmp_path / "data",
                      fetcher=fetcher, limiter=rl)
    report = p.run([(f"https://x.gov.cn/{i}", f"c{i}") for i in range(5)])

    assert report.landed == 2, f"应恰好入库 2 条（配额上限），实际 {report.landed}"
    assert report.count(Outcome.QUOTA_EXHAUSTED) == 1
    assert len(report.results) == 3, "配额耗尽后不应继续处理剩余 URL"


def test_rejected_case_is_not_saved(tmp_path):
    """拒收的不落盘 —— 没有出处的案例进了候选库只会浪费复核时间。"""
    bad = {"fields": {"party_name": {"value": "某某公司", "quote": "某某公司"}}}
    p = _pipeline(tmp_path, payload=bad, page="<html><body></body></html>")
    (r,) = p.process("https://x.gov.cn/1", "c1")
    assert r.outcome in (Outcome.REJECTED, Outcome.FETCH_FAILED)
    assert not (tmp_path / "data" / "structured_candidates" / "c1.json").exists()


def test_circuit_breaker_stops_on_low_extraction_rate(tmp_path):
    """抽取成功率掉下去就停 —— 多半是站点改版，继续跑只产出垃圾候选。"""
    rl, _ = _limiter(cases_per_hour=50, interval=0.0)
    fetcher = Fetcher(gate=_gate(ALLOW_ALL), limiter=rl,
                      client=lambda u: (200, "<html><body>无关内容</body></html>"))

    class _Broken:
        def complete(self, system, user):
            return "模型返回了一段自由文本而不是 JSON"

    p = CrawlPipeline(llm=_Broken(), data_dir=tmp_path / "data",
                      fetcher=fetcher, limiter=rl, min_success_rate=0.5)
    report = p.run([(f"https://x.gov.cn/{i}", f"c{i}") for i in range(20)])

    assert len(report.results) < 20, "应当熔断，而不是把 20 条全跑完"
    assert report.extraction_success_rate < 0.5


def test_duplicate_records_second_source_without_overwriting(tmp_path):
    """多源印证是可信度信号，记录而不丢弃，且主记录不被覆盖。"""
    page = "<html><body>沪市监徐处〔2025〕012号 上海市市场监督管理局 罚款60万元</body></html>"
    p = _pipeline(tmp_path, page=page)
    assert p.process("https://a.gov.cn/1", "c1")[0].outcome == Outcome.LANDED
    (r2,) = p.process("https://b.gov.cn/2", "c2")
    assert r2.outcome == Outcome.DUPLICATE
    assert "文号" in r2.issues[0]


def test_load_existing_seeds_dedup_index(tmp_path):
    """既有案例要先载入，否则会把库里已有的又抓一遍。"""
    d = tmp_path / "data" / "structured"
    d.mkdir(parents=True)
    import json as _j
    (d / "old.json").write_text(_j.dumps({
        "case_id": "old", "penalty_authority": "上海市市场监督管理局",
        "party_name": "某某公司", "publish_date": "2025-06-01",
    }, ensure_ascii=False), encoding="utf-8")

    p = _pipeline(tmp_path)
    assert p.load_existing() == 1
    assert p.process("https://x.gov.cn/1", "c1")[0].outcome == Outcome.DUPLICATE


def test_multi_case_page_yields_one_result_per_case():
    """一个页面含多个案例时，每个案例各自成一条。

    市监总局的典型案例通报是「一篇文章 = 七起案例」。
    按「一个 URL 一个案例」处理会把七个案子揉成一条，
    抽出来的金额和当事人全是错位的 —— 而且不会报错。
    """
    from app.crawler.segment import split_cases
    page = "\n".join([
        "导语部分，现选取三起典型案例予以公布：",
        "一、北京某公司虚假宣传案",
        "经查，当事人宣称普通食品可以治疗糖尿病，" + "违法事实描述充分详尽。" * 20,
        "二、上海某公司发布违法广告案",
        "经查，当事人在广告中使用绝对化用语，" + "违法事实描述充分详尽。" * 20,
        "三、广州某公司虚假宣传案",
        "经查，当事人虚构专利资质，" + "违法事实描述充分详尽。" * 20,
    ])
    segs = split_cases(page)
    assert len(segs) == 3
    assert segs[0].title.startswith("北京某公司")
    assert segs[0].suffix == "_01" and segs[2].suffix == "_03"


def test_single_case_page_is_not_split():
    """地方局的单案公示本来就没有分节 —— 那是正常情况，不是失败。"""
    from app.crawler.segment import split_cases
    segs = split_cases("上海市市场监督管理局对某公司作出行政处罚决定，罚款五万元。" * 6)
    assert len(segs) == 1 and segs[0].suffix == "_00"


def test_short_fragments_are_not_treated_as_cases():
    """目录项那种几个字的小节不能当成案例。"""
    from app.crawler.segment import split_cases
    page = "一、概述\n二、案例\n三、北京某公司虚假宣传案\n" + "详细违法事实描述。" * 20
    segs = split_cases(page)
    assert len(segs) == 1, f"目录项被误当成案例：{[s.title for s in segs]}"


def test_non_round_amount_in_wan_notation_is_verified():
    """「8.33万元」这种非整万写法必须能核上。

    实测踩到的真实案例：原文写「罚款8.33万元」，模型正确抽出 83300，
    但校验器只在整万/整千时生成「万」写法 → 核不上 → 正确结果被当幻觉清空。
    这正是 amount_renderings 注释里警告过的错误，却在非整万金额上重犯了一次。
    """
    assert verify_amount(83300, "对当事人处以罚款8.33万元") is True
    assert "8.33万元" in amount_renderings(83300)


def test_keywords_need_no_quote_at_all():
    """关键词是纯检索辅助：编错只影响召回质量，不影响法律结论。

    按后果衡量它本来就不该有出处要求。实测：归在「要出处」那档时
    7 个案例里仍有 4 个的关键词被丢。
    """
    from app.crawler.extract import FREE_FIELDS
    assert "keywords" in FREE_FIELDS

    llm = _LLM({"fields": {"keywords": {"value": ["虚假宣传", "保健功效"], "quote": None}}})
    r = Extractor(llm).extract(DOC)
    assert r.fields.get("keywords") == ["虚假宣传", "保健功效"]
    assert "keywords" not in r.dropped


def test_critical_fields_still_require_verbatim_quotes():
    """放宽只针对检索辅助字段，高危字段的逐字核对不能被波及。"""
    llm = _LLM({"fields": {
        "penalty_amount": {"value": 9999999, "quote": "罚款九百九十九万元"},
    }})
    r = Extractor(llm).extract(DOC)
    assert "penalty_amount" in r.dropped


def test_missing_legal_basis_is_flagged():
    """没有法条的案例做不了规则 RAG（类案检索按法条关联），但事实仍可能有价值。"""
    r = validate_case(_case(legal_basis=[]), RAW)
    assert not r.rejected
    assert any(i.field == "legal_basis" and i.severity is Severity.FLAG for i in r.issues)


# ══════════════════════════════════════════════════════════════
#  拼接引用与规则兜底（实测踩到的两类误杀）
# ══════════════════════════════════════════════════════════════

_LONG = ("当事人在直播间宣称「3天修复牙龈」「1滴速去灰指甲」「轻松改善高血压」，"
         "违反了《中华人民共和国广告法》第十七条的规定，罚款8.33万元。")


def test_拼接引用不再被整条判成幻觉():
    """模型对列表字段常给「A……B……C」：每段都是原文逐字，合起来却不是原文。

    实测 illegal_claims、product_or_service 就是这么被误杀的。
    把正确的抽取结果当幻觉丢掉，比漏掉一次幻觉更糟 ——
    前者让字段静默变空，后者至少还有痕迹。
    """
    llm = _LLM({"fields": {"illegal_claims": {
        "value": ["3天修复牙龈", "1滴速去灰指甲"],
        "quote": "3天修复牙龈……1滴速去灰指甲",
    }}})
    r = Extractor(llm).extract(_LONG)
    assert r.fields["illegal_claims"] == ["3天修复牙龈", "1滴速去灰指甲"]
    assert "illegal_claims" not in r.dropped


def test_拼接引用里只要有一段是编的就整条丢弃():
    """放宽的只是「允许拆开核」，不是「有一段对就算对」。"""
    llm = _LLM({"fields": {"illegal_claims": {
        "value": ["3天修复牙龈", "包治百病"],
        "quote": "3天修复牙龈……包治百病",   # 后一段原文里没有
    }}})
    r = Extractor(llm).extract(_LONG)
    assert "illegal_claims" in r.dropped


def test_碎片过短的拼接引用不予放行():
    """短片段在长文里撞上纯属偶然，放行等于把引用核对变成走过场。"""
    llm = _LLM({"fields": {"illegal_claims": {
        "value": ["假的"], "quote": "3天……的……当",
    }}})
    assert "illegal_claims" in Extractor(llm).extract(_LONG).dropped


def test_模型漏抽法条时由正则从原文补出():
    """实测 30 条案例丢了 14 条 legal_basis，多数不是核对不上而是模型没抽。"""
    llm = _LLM({"fields": {"penalty_amount": {"value": 83300, "quote": "8.33万元"}}})
    r = Extractor(llm).extract(_LONG)
    assert r.fields["legal_basis"] == ["《中华人民共和国广告法》第十七条"]
    assert r.rule_extracted["legal_basis"] == ["《中华人民共和国广告法》第十七条"]


def test_正则补出的法条不算在幻觉丢弃里():
    """「模型编了」和「模型漏了」是两回事，混在一起会让幻觉率失真。"""
    llm = _LLM({"fields": {"legal_basis": {
        "value": ["《广告法》第十七条"], "quote": None,   # 无引用 → 先被丢弃
    }}})
    r = Extractor(llm).extract(_LONG)
    assert "legal_basis" not in r.dropped
    assert r.fields["legal_basis"] == ["《中华人民共和国广告法》第十七条"]


def test_原文只写有关规定时模型补的条号算推断不算依据():
    """实测原文：「依据《中华人民共和国广告法》有关规定，作出罚没款62.91万元」。

    模型面对「宣称改善骨关节、杀灭幽门螺旋杆菌」几乎必然补出「第十七条」，
    法律上多半对 —— 但**原文没有这句话**。这是引用核对拦不住的一类：
    模型可以照抄「依据《中华人民共和国广告法》有关规定」当 quote，
    那句话确实在原文里，却支撑不了它给的条号。
    """
    text = ("邳州市市场监管局依据《中华人民共和国广告法》有关规定，"
            "对当事人作出罚没款62.91万元的行政处罚。")
    llm = _LLM({"fields": {"legal_basis": {
        "value": ["《中华人民共和国广告法》第十七条"],
        "quote": "依据《中华人民共和国广告法》有关规定",   # 引用真实，但支撑不了条号
    }}})
    r = Extractor(llm).extract(text)
    assert r.fields["legal_basis"] == ["《中华人民共和国广告法》"], "只能记到法规一级"
    assert r.fields["legal_basis_inferred"] == ["《中华人民共和国广告法》第十七条"]


def test_模型给的条号全是推断时legal_basis不得留有条号():
    """原文里连书名号都没有，模型给的条号无任何支撑 —— legal_basis 必须为空。

    只把推断另存一份、却把原值留在 legal_basis，等于什么都没防住。
    """
    llm = _LLM({"fields": {"legal_basis": {
        "value": ["《中华人民共和国广告法》第二十八条"], "quote": "违反广告法",
    }}})
    r = Extractor(llm).extract("当事人的行为违反广告法相关规定。")
    assert "legal_basis" not in r.fields or r.fields["legal_basis"] == []
    assert r.fields["legal_basis_inferred"] == ["《中华人民共和国广告法》第二十八条"]


def test_规则抽取来源写进案例():
    """人工复核时要能一眼看出哪些字段可以直接采信。"""
    llm = _LLM({"fields": {}})
    r = Extractor(llm).extract(_LONG)
    case = to_case(r, "c1", "https://x/", "raw/c1.json")
    assert case["rule_extracted"]["legal_basis"] == ["《中华人民共和国广告法》第十七条"]
