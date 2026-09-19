"""案例自动采集入库测试。

重点不在「能不能跑通」，而在**红线是不是真的过不去**：
robots 取不到会不会照抓、超出允许域会不会照抓、
自动产出会不会给自己盖「已核验」章、抽出来的字段能不能回溯到原文。

这些一旦失守，污染的是一个要用来支撑法律判断的案例库，
而污染进去的假事实很难再被发现。
"""

import io
import json
import urllib.error
from pathlib import Path

import pytest
import yaml

from app.ingest.fetch import (
    MIN_DELAY_SECONDS, Fetcher, FetchError, LoginRequired,
    RateLimiter, RawHtmlStore, RobotsDenied, RobotsGate,
)
from app.ingest.parse import discover_detail_urls, parse_html, split_cases
from app.ingest.pipeline import IngestPipeline
from app.ingest.registry import CrawlMode, Priority, Registry, Source
from app.ingest.structure import (
    RuleCatalog, build_candidate, extract_authority, extract_legal_basis,
    extract_party, extract_penalty_amount, extract_publish_date,
)

REFS = Path(__file__).resolve().parents[2] / "data"
REAL_PAGE = REFS / "raw_html" / "samr_typical_ads__2ad160ae3056.json"
RULE_JSON = REFS / "rules" / "advertising_law_2021.json"
needs_refs = pytest.mark.skipif(not REAL_PAGE.exists(), reason="根目录真实样例未提供")


def _source(**kw) -> Source:
    base = dict(
        source_id="t", source_name="测试源", source_type="test",
        priority=Priority.P0, base_url="https://example.gov.cn",
        allowed_domains=("example.gov.cn",), crawl_mode=CrawlMode.MANUAL_SEED,
    )
    base.update(kw)
    return Source(**base)


class _FakeOpener:
    """假 opener：按 URL 返回内容或抛错，用于在不联网的情况下测合规闸门。"""

    def __init__(self, routes: dict):
        self.routes = routes

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        val = self.routes.get(url)
        if val is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(val, Exception):
            raise val
        return _FakeResp(url, val)


class _FakeResp(io.BytesIO):
    def __init__(self, url, text):
        super().__init__(text.encode("utf-8"))
        self._url = url
        self.headers = _FakeHeaders()

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class _FakeHeaders:
    def get_content_charset(self):
        return "utf-8"


# ══ 合规闸门 ═══════════════════════════════════════════════════


def test_robots_fails_closed_when_unreachable():
    """robots.txt 取不到时必须拒绝抓取。

    取不到就无法证明对方允许，此时继续抓属于赌运气。
    这条一旦放开，整个管线的合规声明就不成立了。
    """
    gate = RobotsGate(opener=_FakeOpener({
        "https://example.gov.cn/robots.txt": urllib.error.URLError("网络不可达"),
    }))
    with pytest.raises(RobotsDenied, match="无法获取"):
        gate.check("https://example.gov.cn/a.html")


def test_robots_disallow_is_respected():
    gate = RobotsGate(opener=_FakeOpener({
        "https://example.gov.cn/robots.txt": "User-agent: *\nDisallow: /private/\n",
    }))
    gate.check("https://example.gov.cn/public/a.html")          # 不抛错
    with pytest.raises(RobotsDenied, match="不允许抓取"):
        gate.check("https://example.gov.cn/private/a.html")


def test_missing_robots_file_is_treated_as_allowed():
    """404 说明站点没设 robots，按惯例视为未设限制——这与「取不到」是两回事。"""
    gate = RobotsGate(opener=_FakeOpener({}))   # 全部 404
    gate.check("https://example.gov.cn/a.html")


def test_rate_limiter_enforces_hard_floor():
    """配置可以调大间隔，不能调小到硬下限以下。"""
    lim = RateLimiter(default_delay=0.001)
    assert lim.default_delay >= MIN_DELAY_SECONDS
    lim.set_delay("example.gov.cn", 0.0)
    assert lim._delay["example.gov.cn"] >= MIN_DELAY_SECONDS


def test_fetch_rejects_url_outside_allowed_domains():
    """越域抓取要挡住：源声明了只抓某个域，就不能顺着链接跑到别处去。"""
    f = Fetcher(offline_html={"https://evil.example/x": "<html></html>"})
    with pytest.raises(FetchError, match="allowed_domains"):
        f.fetch("https://evil.example/x", _source())


def test_login_page_is_abandoned_not_bypassed():
    """需要登录就放弃，不尝试绕过。"""
    opener = _FakeOpener({
        "https://example.gov.cn/robots.txt": "User-agent: *\nAllow: /\n",
        "https://example.gov.cn/a.html": urllib.error.HTTPError(
            "https://example.gov.cn/a.html", 403, "Forbidden", {}, None),
    })
    f = Fetcher(robots=RobotsGate(opener=opener), limiter=RateLimiter(), _opener=opener)
    with pytest.raises(LoginRequired):
        f.fetch("https://example.gov.cn/a.html", _source())


# ══ 源注册表 ═══════════════════════════════════════════════════


def test_p3_source_cannot_be_fact_source():
    """律所文章、媒体报道仅作口径参考，不得作处罚事实依据。"""
    assert not Priority.P3.can_be_fact_source
    assert all(p.can_be_fact_source for p in (Priority.P0, Priority.P1, Priority.P2))


def test_registry_loads_project_sources():
    reg = Registry.load(Path(__file__).resolve().parents[1] / "app" / "ingest" / "sources.yaml")
    assert reg.sources
    ids = {s.source_id for s in reg.sources}
    assert "samr_typical_ads" in ids


def test_pipeline_skips_p3_source(tmp_path):
    pipe = IngestPipeline(data_root=tmp_path, fetcher=Fetcher(offline_html={}))
    result = pipe.run_source(_source(priority=Priority.P3, detail_urls=("https://example.gov.cn/a",)))
    assert result.structured == 0
    assert any("不得作为处罚事实依据" in e for e in result.errors)


# ══ 解析与发现 ═════════════════════════════════════════════════


def test_discover_requires_explicit_pattern():
    """没配详情页正则就不发现任何链接。

    宁可发现不到，也不要把栏目导航、分页器当成案例抓回来——
    那等于往处罚案例库里掺不是处罚案例的东西。
    """
    html = '<a href="/art/2026/art_%s.html">案例</a>' % ("a" * 32)
    page = parse_html(html, base_url="https://example.gov.cn/list")
    assert discover_detail_urls(page, _source()) == []

    src = _source(detail_url_pattern=r"/art/\d{4}/art_[0-9a-f]{32}\.html$")
    assert len(discover_detail_urls(page, src)) == 1


def test_discover_stays_within_allowed_domains():
    html = ('<a href="https://other.example/art/2026/art_%s.html">外域</a>' % ("b" * 32))
    page = parse_html(html, base_url="https://example.gov.cn/list")
    src = _source(detail_url_pattern=r"art_[0-9a-f]{32}\.html$")
    assert discover_detail_urls(page, src) == []


def test_parse_drops_script_and_keeps_text():
    page = parse_html(
        "<html><head><title>标题</title></head><body>"
        "<script>var x=1;</script><p>正文一段</p><p>正文二段</p></body></html>",
        base_url="https://example.gov.cn/a",
    )
    assert page.title == "标题"
    assert "var x" not in page.full_text
    assert "正文一段" in page.paragraphs


# ══ 一页多案切分（最要紧的一条）═════════════════════════════════


@needs_refs
def test_split_real_multi_case_page():
    """真实的「十起典型案例」页必须切成 10 条。

    不切分的话整页被当成一个案例，只有第一条的处罚事实被抽走，
    **另外九条悄无声息地丢掉**——库里看着多了一条记录，实际漏了九条，
    而且从结果上完全看不出来漏了。
    """
    d = json.loads(REAL_PAGE.read_text(encoding="utf-8"))
    page = parse_html(d["html"], base_url=d["source_url"])
    sections = split_cases(page)

    assert len(sections) == 10, f"应切出 10 个案例，实际 {len(sections)}"
    for s in sections:
        assert "案" in s.title
        assert len(s.full_text) > 40


def test_split_does_not_fire_on_ordinary_numbered_list():
    """普通的「一、二、」条列（政策文件分点）不该被当成案例边界。"""
    page = parse_html(
        "<html><body><p>一、总体要求</p><p>要坚持依法治理。</p>"
        "<p>二、主要任务</p><p>要加强监管。</p></body></html>",
        base_url="https://example.gov.cn/a",
    )
    assert split_cases(page) == []


# ══ 字段抽取 ═══════════════════════════════════════════════════


@pytest.mark.parametrize("text,expected", [
    ("对当事人作出罚款60万元的行政处罚", 600000),
    ("作出罚款600000元的行政处罚", 600000),
    ("作出罚没款28.72万元的行政处罚", 287200),
    ("罚款人民币10.5万元", 105000),
])
def test_extract_amount(text, expected):
    r = extract_penalty_amount(text)
    assert r is not None and r.value == expected


def test_amount_extraction_ignores_non_penalty_amounts():
    """涉案货值不是处罚金额。抽错了比空着更糟——它会被当成处罚力度参考。"""
    assert extract_penalty_amount("涉案货值金额30万元，尚未作出处罚决定") is None


def test_extract_authority_and_party_from_case_title():
    title = "一、广东省广州市番禺区市场监管局查处广州简美健康科技有限公司违法广告案"
    assert extract_authority(title).value == "广东省广州市番禺区市场监管局"
    assert extract_party(title).value == "广州简美健康科技有限公司"


def test_extract_publish_date():
    assert extract_publish_date("发布时间：2026-01-31 11:00").value == "2026-01-31"


def test_legal_basis_keeps_article_none_when_source_gives_none():
    """原文只写「依据《广告法》有关规定」时，条号就该是 None。

    补一个条号进去是编造法律依据——AGENTS.md 的头号红线。
    """
    laws = extract_legal_basis("依据《中华人民共和国广告法》有关规定作出处罚")
    assert len(laws) == 1
    assert laws[0].value["law"] == "中华人民共和国广告法"
    assert laws[0].value["article"] is None


def test_legal_basis_parses_article_number():
    laws = extract_legal_basis("违反《中华人民共和国广告法》第十七条的规定")
    assert laws[0].value["article"] == 17


@needs_refs
def test_rule_catalog_maps_article_to_rule_id():
    cat = RuleCatalog.load(RULE_JSON)
    assert cat.lookup("中华人民共和国广告法", 17) == "ADLAW-017"
    assert cat.lookup("广告法", 28) == "ADLAW-028"
    assert cat.lookup("广告法", None) is None


# ══ 候选条目契约 ═══════════════════════════════════════════════


SAMPLE = (
    "一、广东省广州市番禺区市场监管局查处广州简美健康科技有限公司违法广告案\n"
    "经查，该公司发布的普通商品广告中含有“促进眼角膜修复”等内容。\n"
    "2025年11月，广东省广州市番禺区市场监管局依据《中华人民共和国广告法》"
    "有关规定，对当事人作出罚款60万元的行政处罚。"
)


def _candidate(**kw):
    base = dict(
        case_id="t__01", title="测试案", source_name="市监总局",
        source_url="https://example.gov.cn/a", source_type="official_typical_case",
        full_text=SAMPLE, raw_text_path="data/raw_text/t.json",
    )
    base.update(kw)
    return build_candidate(**base)


def test_candidate_review_status_is_always_pending():
    """自动管线不给自己的产出盖「已核验」章。

    让 AI 为自己的抽取结果背书，等于取消了人工核验环节，
    而这个库是要拿来支撑法律判断的。
    """
    assert _candidate()["review_status"] == "pending_review"


def test_candidate_keeps_source_url_and_raw_text_path():
    """AGENTS.md 要求所有结构化结果保留这两个字段以便回溯。"""
    c = _candidate()
    assert c["source_url"] and c["raw_text_path"]


def test_every_extracted_field_points_back_to_source_text():
    """**每个抽出的字段都要能在原文里定位到**。

    这是「不得编造」的结构性保障：拿 span 去原文切一刀，
    切出来的必须就是它声称的那段引用。对不上就说明这个值来路不明。
    """
    c = _candidate()
    for name, ev in c["_ingest"]["evidence"].items():
        s, e = ev["span"]
        assert SAMPLE[s:e] == ev["quote"], f"字段 {name} 的出处对不上原文"


def test_candidate_records_what_it_could_not_extract():
    c = _candidate(full_text="一段没有任何处罚要素的文字。")
    ing = c["_ingest"]
    assert "penalty_amount" in ing["needs_review"]
    assert set(ing["fact_fields_missing"]) >= {"penalty_amount", "penalty_authority"}
    assert c["penalty_amount"] is None, "抽不到就留空，不能填 0——0 元罚款是另一回事"


def test_illegal_claims_always_need_review():
    """引号里的内容不一定是违法宣称，也可能是产品名，一律交人筛。"""
    c = _candidate()
    assert "促进眼角膜修复" in c["illegal_claims"]
    assert "illegal_claims" in c["_ingest"]["needs_review"]


def test_vector_text_is_verbatim_not_paraphrase():
    """vector_text 取原文摘录，不做转述——转述会失真。"""
    c = _candidate()
    assert c["_ingest"]["vector_text_mode"] == "verbatim_excerpt"
    assert c["vector_text"]
    assert c["vector_text"].replace("\n", "") in SAMPLE.replace("\n", "")


# ══ 增量 ═══════════════════════════════════════════════════════


def test_incremental_skips_unchanged_pages(tmp_path):
    """同一页面内容没变，第二轮不该重复入库。"""
    url = "https://example.gov.cn/a.html"
    html = f"<html><body><p>{SAMPLE}</p></body></html>"
    src = _source(detail_urls=(url,))
    pipe = IngestPipeline(data_root=tmp_path, fetcher=Fetcher(offline_html={url: html}))

    first = pipe.run_source(src)
    assert first.fetched == 1 and first.structured == 1

    second = pipe.run_source(src)
    assert second.fetched == 0
    assert second.skipped_known == 1
    assert second.structured == 0


def test_raw_html_is_written_for_audit(tmp_path):
    """原始页面必须落盘：AGENTS.md 明令不得删除，抽取规则改了也要能重跑。"""
    url = "https://example.gov.cn/a.html"
    src = _source(detail_urls=(url,))
    pipe = IngestPipeline(
        data_root=tmp_path,
        fetcher=Fetcher(offline_html={url: f"<html><body><p>{SAMPLE}</p></body></html>"}),
    )
    pipe.run_source(src)

    saved = list((tmp_path / "raw_html").glob("*.json"))
    assert len(saved) == 1
    d = json.loads(saved[0].read_text(encoding="utf-8"))
    assert d["source_url"] == url
    assert d["content_sha256"] and d["html"]
