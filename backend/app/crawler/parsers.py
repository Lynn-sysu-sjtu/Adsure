"""各数据源的列表页解析器。

每个源一个解析器：站点结构各不相同，通用解析器在这个场景里做不出来。
解析器只负责「从列表页找出详情页链接」，不负责判断内容。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin

logger = logging.getLogger(__name__)

# samr 详情页形如 /xw/zj/art/2026/art_<32位hash>.html
_ART_HREF = re.compile(r"art_[0-9a-f]{16,}\.html$", re.I)

_A_TAG = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*["']([^"']*)["']""")
_TAGS = re.compile(r"<[^>]+>")

# 只要与广告 / 宣传 / 食药妆 相关的案例通报。
# 总局新闻里还有反垄断、计量、质量等大量典型案例，与本项目无关 ——
# 抓回来只会占满人工复核的产能。
_CASE_KIND = re.compile(r"典型案例|违法广告|虚假宣传|查处|曝光台?|处罚")
_TOPIC = re.compile(r"广告|宣传|食品|保健|化妆品|医疗|药|直播|带货|消费|老年")

# 会通过上面两条却与广告法无关的主题。
# 「制止食品浪费」走的是《反食品浪费法》，「失信名单」不是案例通报体裁 ——
# 它们抓回来不会被质量门禁拦下（本身是合规的处罚案例），只会占满人工复核产能。
_EXCLUDE = re.compile(r"食品浪费|失信名单|计量|特种设备|反垄断|经营者集中")


@dataclass
class Link:
    url: str
    title: str


def _iter_anchors(html: str, base_url: str):
    """从 HTML 片段里逐个取出 <a>，产出 (绝对URL, 标题)。

    标题优先取 title 属性 —— 列表页的可见文字常被 CSS 截断成两行并混入
    换行与空白，title 属性才是完整标题。
    """
    for m in _A_TAG.finditer(html or ""):
        attrs = dict(_ATTR.findall(m.group(1)))
        href = attrs.get("href", "")
        if not href:
            continue
        title = attrs.get("title") or _TAGS.sub("", m.group(2))
        yield urljoin(base_url, href), re.sub(r"\s+", "", title)


def parse_samr_list(html: str, base_url: str, topical_only: bool = True) -> list[Link]:
    """从市监总局列表页（静态 HTML 或接口返回的 HTML 片段）抽出详情页链接。

    topical_only=True 时只保留与广告/宣传/食药妆相关的案例通报。
    """
    seen: set[str] = set()
    out: list[Link] = []

    for url, title in _iter_anchors(html, base_url):
        if not _ART_HREF.search(url.split("?")[0]):
            continue
        if url in seen or len(title) < 6:
            continue
        seen.add(url)

        if topical_only:
            if not _CASE_KIND.search(title) or not _TOPIC.search(title):
                continue
            if _EXCLUDE.search(title):
                logger.debug("按主题排除：%s", title)
                continue
        out.append(Link(url, title))

    logger.info("列表页解析出 %d 条%s链接", len(out), "相关" if topical_only else "")
    return out


# ══════════════════════════════════════════════════════════════
#  总局列表页的翻页接口
# ══════════════════════════════════════════════════════════════
#
# 列表条目不在静态 HTML 里 —— 页面骨架加载后，由 CMS（jpaas 发布服务）的
# 内容单元自己调下面这个接口把条目取回来渲染。所以纯 HTTP 拿 /xw/zj/
# 只能得到 3KB 空壳。
#
# 这个接口是**公开接口**：没有登录、没有令牌、没有验证码、没有 Referer 校验，
# 参数就是页面上写死的栏目标识。它是这个公开页面自己的数据源，读它和读
# 渲染后的 HTML 是同一件事，不涉及任何鉴权或访问控制。
# 详情页本身是静态的，不受影响。
#
# 参数取自栏目页 /xw/zj/ 的内容单元配置。换栏目只需换这三个 ID。

_SAMR_API = ("https://www.samr.gov.cn"
             "/api-gateway/jpaas-publish-server/front/page/build/unit")

SAMR_COLUMNS: dict[str, dict[str, str]] = {
    # 总局要闻：典型案例通报的主要发布位置
    "zj": {
        "base": "https://www.samr.gov.cn/xw/zj/",
        "webId": "29e9522dc89d4e088a953d8cede72f4c",
        "pageId": "39cd9de1f309431483ef3008309f39ca",
        "tplSetId": "5c30fb89ae5e48b9aefe3cdf49853830",
    },
}


def samr_api_url(page_no: int, column: str = "zj", page_size: int = 50) -> str:
    """构造某一页列表的接口地址。

    page_size 取大一点是**更礼貌**而不是更激进：同样的条目数，请求次数更少。
    """
    col = SAMR_COLUMNS[column]
    return _SAMR_API + "?" + urlencode({
        "webId": col["webId"],
        "pageId": col["pageId"],
        "parseType": "bulidstatic",
        "pageType": "column",
        "tagId": "内容区域",
        "tplSetId": col["tplSetId"],
        "paramJson": json.dumps({"pageNo": page_no, "pageSize": page_size},
                                ensure_ascii=False),
    })


def samr_list_urls(pages: int = 1, column: str = "zj", page_size: int = 50) -> list[str]:
    """要扫的列表页接口地址（第 1..pages 页）。"""
    return [samr_api_url(i, column, page_size) for i in range(1, max(pages, 1) + 1)]


def parse_samr_api(body: str, column: str = "zj",
                   topical_only: bool = True) -> list[Link]:
    """解析翻页接口的返回。

    返回体是 JSON，正文在 data.html —— 一段 HTML 片段。取出片段后交给
    parse_samr_list，与静态列表页走同一条解析路径。
    """
    try:
        payload = json.loads(body or "")
    except (json.JSONDecodeError, TypeError):
        logger.warning("列表接口返回的不是 JSON（前 120 字符：%r）", (body or "")[:120])
        return []

    frag = ((payload.get("data") or {}).get("html")) or ""
    if not frag:
        logger.warning("列表接口返回里没有 data.html，字段为：%s", list(payload.keys()))
        return []

    return parse_samr_list(frag, SAMR_COLUMNS[column]["base"], topical_only)


# ══════════════════════════════════════════════════════════════
#  地方市场监管局（P1）列表页解析器
# ══════════════════════════════════════════════════════════════
#
# 各地方局的栏目页/详情页结构各不相同，无法做通用解析器。这里给出骨架：
#   · local_samr_list_urls / parse_local_samr_list 依赖「已确认的列表页 URL」，
#     未确认前 sources.yaml 里 local_samr 源保持 enabled=false、list_url=null，
#     跑 crawler 会打印提示并退出，不会对着猜的 URL 反复请求（见 sources.yaml 注释）。
# 启用一个地方局源的步骤：
#   1. 人工打开该局「行政处罚/行政处罚决定」公开栏目，确认列表页与详情页结构；
#   2. 在 sources.yaml 填入 base_url / list_url，并把 list 页的翻页参数交给
#      local_samr_list_urls（或改 parser）；
#   3. 确认详情页 href 形态后，在 parse_local_samr_list 的 _ART_HREF 或新正则里放宽匹配；
#   4. enabled: true 后再跑 crawler --source local_samr。
_PENALTY_TITLE = re.compile(r"行政处罚|处罚决定|处罚信息|处罚公示|查处")


def local_samr_list_urls(list_url: str, pages: int = 1, page_param: str = "page") -> list[str]:
    """构造地方局列表分页 URL。

    需要人工确认该局的分页参数名（常见 page / pageNo / index）后调用。
    list_url 未确认时返回空列表 —— 不猜 URL。
    """
    if not list_url:
        logger.warning("local_samr 源未配置 list_url，无法构造列表页。")
        return []
    sep = "&" if "?" in list_url else "?"
    return [f"{list_url}{sep}{page_param}={i}" for i in range(1, max(pages, 1) + 1)]


def parse_local_samr_list(html: str, base_url: str, topical_only: bool = True) -> list[Link]:
    """从地方局列表页抽详情页链接（通用锚点解析）。

    与 parse_samr_list 同一套锚点遍历；按标题含「处罚」过滤，避免把通知/新闻当案例。
    """
    seen: set[str] = set()
    out: list[Link] = []
    for url, title in _iter_anchors(html or "", base_url):
        if url in seen or len(title) < 6:
            continue
        seen.add(url)
        if topical_only and not _PENALTY_TITLE.search(title):
            continue
        out.append(Link(url, title))
    logger.info("地方局列表页解析出 %d 条处罚链接", len(out))
    return out


# ══════════════════════════════════════════════════════════════
#  信用中国（P2）—— 仅骨架
# ══════════════════════════════════════════════════════════════
# 实测 creditchina.gov.cn 返回 HTTP 412（反爬）且列表多为前端渲染。
# 在找到「无需登录、无验证码、静态可直抓」的公开页/接口之前，不允许启用，
# 也不写猜测的 URL。启用前必须：人工确认公开入口 → 填 sources.yaml → 实现本解析器。
def creditchina_list_urls(list_url: str, pages: int = 1) -> list[str]:
    if not list_url:
        logger.warning("creditchina 源未配置 list_url，无法构造列表页。")
        return []
    return [f"{list_url}&pageNo={i}" for i in range(1, max(pages, 1) + 1)]


def parse_creditchina_list(html: str, base_url: str, topical_only: bool = True) -> list[Link]:
    """信用中国列表解析骨架：确认公开静态页结构后实现。"""
    raise NotImplementedError(
        "信用中国（P2）解析器未实现：须先人工确认存在可直抓的公开静态页/接口，"
        "并确认列表与详情页结构后，再实现本函数并启用 sources.yaml 中的 creditchina 源。"
    )


# ══════════════════════════════════════════════════════════════
#  上海市市场监督管理局 · 行政处罚典型案例（P1）
# ══════════════════════════════════════════════════════════════
# 列表页：https://scjgj.sh.gov.cn/1073/index.html（静态 HTML）
# 详情页：/1073/YYYYMMDD/<32位hex>.html（静态文章页，详情解析走通用 html_to_text）
_SHANGHAI_LIST = "https://scjgj.sh.gov.cn/1073/index.html"
_SHANGHAI_DETAIL_HREF = re.compile(r"/1073/\d{8}/[0-9a-f]{32}\.html$", re.I)
_SHANGHAI_TOPIC = re.compile(r"广告|宣传|食品|保健|化妆品|医疗|药|直播|带货|消费|价格|老年|互联网")
_SHANGHAI_EXCLUDE = re.compile(r"商业秘密|电动自行车|儿童|学生|质量违法|专利|商标")


def shanghai_list_urls(pages: int = 1) -> list[str]:
    """上海行政处罚典型案例列表页分页：index.html, index_2.html ... index_N.html。"""
    urls = [_SHANGHAI_LIST]
    urls.extend(
        f"https://scjgj.sh.gov.cn/1073/index_{i}.html"
        for i in range(2, max(pages, 1) + 1)
    )
    return urls


def parse_shanghai_zfxxgkml(html: str, base_url: str = "https://scjgj.sh.gov.cn",
                            topical_only: bool = True) -> list[Link]:
    """解析上海 /1073/index.html：只取本栏目静态详情页，并按广告主题过滤。"""
    seen: set[str] = set()
    out: list[Link] = []
    for url, title in _iter_anchors(html or "", base_url):
        path = url.split("?")[0]
        if not _SHANGHAI_DETAIL_HREF.search(path):
            continue
        if url in seen or len(title) < 6:
            continue
        seen.add(url)
        if topical_only:
            if not _SHANGHAI_TOPIC.search(title) or _SHANGHAI_EXCLUDE.search(title):
                logger.debug("上海列表按主题跳过：%s", title)
                continue
        out.append(Link(url, title))
    logger.info("上海列表页解析出 %d 条广告相关处罚链接", len(out))
    return out


# ══════════════════════════════════════════════════════════════
#  国家新闻出版署 · 通知公示（游戏版号 / 未成年人 / 防沉迷，P0/P1）
# ══════════════════════════════════════════════════════════════
# 列表页：https://www.nppa.gov.cn/xxfb/tzgs/（静态 HTML）
# 详情页：/xxfb/tzgs/YYYYMM/tYYYYMMDD_<id>.html（静态文章页）
_NPPA_LIST = "https://www.nppa.gov.cn/xxfb/tzgs/"
_NPPA_DETAIL_HREF = re.compile(r"/xxfb/tzgs/20\d{4}/t20\d{6}_\d+\.html$", re.I)
_NPPA_TOPIC = re.compile(r"游戏|版号|未成年|防沉迷|约谈|处罚|整改|运营|充值|网络出版")
_NPPA_EXCLUDE = re.compile(r"图书|期刊|报纸|古籍|出版基金|审读|教材|辞书")


def nppa_list_urls(pages: int = 1) -> list[str]:
    """新闻出版署通知公示列表页。分页方式待确认，先取首页。"""
    return [_NPPA_LIST]


_NPPA_A = re.compile(r'<a\b[^>]*href="([^"]*t\d{8}_\d+\.html)"[^>]*>(.*?)</a>', re.S | re.I)
_NPPA_TITLE = re.compile(r"_(?:docTitle|docTits)\s*=\s*['\"]([^'\"]+)['\"]")


def parse_nppa_tzgs(html: str, base_url: str = "https://www.nppa.gov.cn",
                    topical_only: bool = True) -> list[Link]:
    """解析新闻出版署通知公示列表。

    该站列表标题不在 anchor 的 title 属性/文本里，而是藏在锚点内的
    ``<script>var _docTitle = '标题'</script>`` 中，因此单独抽取。
    """
    seen: set[str] = set()
    out: list[Link] = []
    for m in _NPPA_A.finditer(html or ""):
        href = m.group(1)
        tm = _NPPA_TITLE.search(m.group(2) or "")
        title = tm.group(1).strip() if tm else ""
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        if topical_only:
            if not title or not _NPPA_TOPIC.search(title):
                continue
            if _NPPA_EXCLUDE.search(title):
                logger.debug("nppa 列表按主题跳过：%s", title)
                continue
        out.append(Link(url, title))
    logger.info("nppa 列表页解析出 %d 条游戏相关链接", len(out))
    return out
