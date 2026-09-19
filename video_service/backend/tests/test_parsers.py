# -*- coding: utf-8 -*-
"""列表页解析器测试。

重点不在「能不能解析正常返回」，而在**返回不正常时会怎样**：
站点改版、接口报错页、栏目下线 —— 这些都会让解析器拿到不是它预期的东西。
静默返回空列表是可接受的（抓不到就是抓不到），静默抛异常打断整轮抓取不是。
"""

from __future__ import annotations

import json

import pytest

from app.crawler.parsers import (
    Link,
    parse_samr_api,
    parse_samr_list,
    samr_api_url,
    samr_list_urls,
)

_HREF = "/xw/zj/art/2026/art_{}.html"


def _anchor(h: str, title: str, inner: str | None = None) -> str:
    return (f'<li><a href="{_HREF.format(h)}" target="_blank" title="{title}">'
            f'{inner if inner is not None else title}</a></li>')


def _envelope(*anchors: str) -> str:
    return json.dumps({
        "success": True,
        "data": {"html": '<div class="page-content"><ul>'
                         + "".join(anchors) + "</ul></div>"},
    }, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════
#  接口返回的解析
# ══════════════════════════════════════════════════════════════

def test_api_envelope_yields_links():
    body = _envelope(
        _anchor("a" * 32, "市场监管总局公布十起违法广告典型案例"),
        _anchor("b" * 32, "市场监管总局集中发布第六批直播电商领域典型案例"),
    )
    links = parse_samr_api(body)
    assert [l.title for l in links] == [
        "市场监管总局公布十起违法广告典型案例",
        "市场监管总局集中发布第六批直播电商领域典型案例",
    ]
    assert all(l.url.startswith("https://www.samr.gov.cn/xw/zj/art/") for l in links)


def test_relative_href_is_resolved_against_column_base():
    links = parse_samr_api(_envelope(_anchor("c" * 32, "十起违法广告典型案例")))
    assert links[0].url == f"https://www.samr.gov.cn{_HREF.format('c' * 32)}"


def test_title_attribute_wins_over_truncated_inner_text():
    """列表页的可见文字常被模板折行/截断，title 属性才是完整标题。

    标题是主题过滤的唯一依据 —— 拿到截断标题会让过滤结果变得不可预期。
    """
    body = _envelope(_anchor("d" * 32, "市场监管总局公布十起违法广告典型案例",
                             inner="市场监管总局公布十起违法广\n告典型案例"))
    assert parse_samr_api(body)[0].title == "市场监管总局公布十起违法广告典型案例"


def test_inner_text_used_when_title_attribute_absent():
    frag = (f'<a href="{_HREF.format("e" * 32)}">'
            "市场监管总局公布十起违法广告典型案例</a>")
    body = json.dumps({"data": {"html": frag}}, ensure_ascii=False)
    assert parse_samr_api(body)[0].title == "市场监管总局公布十起违法广告典型案例"


# ══════════════════════════════════════════════════════════════
#  返回不是预期形状时
# ══════════════════════════════════════════════════════════════

def test_html_error_page_returns_empty_not_exception():
    """接口报错时站点会返回 HTML 错误页而不是 JSON。

    整轮抓取要能继续走到下一页，不能被一页的异常打断。
    """
    assert parse_samr_api("<html><body>502 Bad Gateway</body></html>") == []


def test_json_without_data_html_returns_empty():
    assert parse_samr_api(json.dumps({"success": False, "message": "参数错误"})) == []


def test_empty_body_returns_empty():
    assert parse_samr_api("") == []


def test_valid_json_wrong_shape_returns_empty():
    assert parse_samr_api(json.dumps({"data": {"list": [1, 2, 3]}})) == []


# ══════════════════════════════════════════════════════════════
#  主题过滤
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("title", [
    "市场监管总局公布十起违法广告典型案例",
    "市场监管总局集中发布第六批直播电商领域典型案例",
    "市场监管总局公布七起老年人药品、保健品虚假宣传典型案例",
    "市场监管总局曝光2023年“神医”“神药”广告违法典型案例",
])
def test_ad_law_bulletins_are_kept(title):
    assert len(parse_samr_api(_envelope(_anchor("f" * 32, title)))) == 1


@pytest.mark.parametrize("title", [
    # 走《反食品浪费法》，不是广告法 —— 抓回来会占满人工复核产能
    "市场监管部门公布第九批制止食品浪费行政处罚典型案例",
    # 不是案例通报体裁
    "市场监管总局曝光一批侵害消费者权益严重违法失信名单",
    # 主题与广告合规无关
    "市场监管总局公布第二批经营者集中反垄断审查典型案例",
])
def test_off_topic_bulletins_are_dropped(title):
    assert parse_samr_api(_envelope(_anchor("g" * 32, title))) == []


def test_topical_filter_can_be_turned_off():
    body = _envelope(_anchor("1" * 32, "2026年全国“质量月”活动全面启动"))
    assert parse_samr_api(body) == []
    frag = json.loads(body)["data"]["html"]
    assert len(parse_samr_list(frag, "https://www.samr.gov.cn/xw/zj/",
                               topical_only=False)) == 1


def test_non_article_links_are_ignored():
    """列表片段里还有分页、栏目导航等链接，它们不是详情页。"""
    frag = ('<a href="/xw/zj/index.html" title="返回">返回列表</a>'
            '<a href="javascript:void(0)" title="下一页">下一页</a>'
            + _anchor("2" * 32, "市场监管总局公布十起违法广告典型案例"))
    body = json.dumps({"data": {"html": frag}}, ensure_ascii=False)
    assert len(parse_samr_api(body)) == 1


def test_duplicate_urls_collapse():
    body = _envelope(
        _anchor("3" * 32, "市场监管总局公布十起违法广告典型案例"),
        _anchor("3" * 32, "市场监管总局公布十起违法广告典型案例"),
    )
    assert len(parse_samr_api(body)) == 1


# ══════════════════════════════════════════════════════════════
#  接口地址构造
# ══════════════════════════════════════════════════════════════

def test_api_url_carries_pagination_in_param_json():
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(samr_api_url(3, page_size=50)).query)
    assert json.loads(q["paramJson"][0]) == {"pageNo": 3, "pageSize": 50}
    assert q["tagId"] == ["内容区域"]


def test_list_urls_are_one_per_page_and_distinct():
    urls = samr_list_urls(4)
    assert len(urls) == 4 == len(set(urls))


def test_pages_zero_still_yields_first_page():
    """扫 0 页是没有意义的输入，退化成扫第一页而不是静默什么都不做。"""
    assert len(samr_list_urls(0)) == 1


def test_unknown_column_fails_loudly():
    """栏目 ID 写错要立刻报错 —— 静默用错栏目会抓回一堆无关内容。"""
    with pytest.raises(KeyError):
        samr_api_url(1, column="不存在的栏目")
