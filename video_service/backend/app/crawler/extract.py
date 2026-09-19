"""结构化抽取：规则优先，大模型兜底，逐字段核对原文。

反幻觉的核心机制是**引用核对**：

    要求模型对每个字段附上它依据的原文片段（quote），
    抽完之后逐条回原文里搜这个片段。搜不到 = 模型编的 = 该字段作废。

这比「让模型别编」有效得多 —— 后者是请求，前者是校验。
而且校验不需要另一个模型，字符串匹配就够。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_JSON = re.compile(r"\{.*\}", re.S)
_WS = re.compile(r"[\s　]+")

# 这三个字段编造的后果最严重：报告里引用一个不存在的罚款金额或法条，
# 比不引用糟糕得多。所以它们**必须**能在原文定位，定位不到一律清空。
CRITICAL_FIELDS = ("penalty_amount", "penalty_authority", "legal_basis")

# 字段按**编错的后果**分三档，档次决定核对严格程度：
#
#   默认（逐字核对）  当事人、机关、金额、法条…… 编错会让报告引用不存在的事实
#   NARRATIVE（要出处） 事实摘要、监管逻辑、检索描述 —— 是概括，但要指出依据哪一段
#   FREE（不要出处）   关键词 —— 纯检索辅助，编错只影响召回质量，不影响法律结论
#
# keywords 起初归在最严那档，实测 7 个案例里 6 个被判幻觉丢弃 ——
# 关键词本来就是提炼的，要求逐字出现等于要求它不许是关键词。
# 改到 NARRATIVE 后仍丢了 4 个，因为模型对这种全局性字段常给不出单一出处。
# 按后果衡量，它本来就不该有出处要求。
NARRATIVE_FIELDS = ("facts_summary", "regulatory_logic", "vector_text")
FREE_FIELDS = ("keywords",)

SYSTEM = """你从中国行政处罚决定书原文中抽取结构化字段，服务于广告合规研究。

严格遵守：
1. **每个字段都必须附上 quote —— 你据以判断的原文片段，逐字照抄，不得改写。**
2. 原文里没有的信息，value 填 null，quote 填 null。**不要推测、不要补全、不要合并常识。**
3. penalty_amount 只填阿拉伯数字（单位：元）。原文写「六十万元」就填 600000，\
但 quote 仍要照抄「六十万元」。
4. legal_basis 填法条名称与条款，逐条列出，如「《中华人民共和国广告法》第十七条」。
5. facts_summary / regulatory_logic / vector_text 是你的概括，quote 填你概括所依据的主要段落。
6. vector_text 必须是**自然语言场景描述**（40 字以上完整句子），\
用于语义检索，不得写成关键词堆砌。

只输出 JSON，不要解释。"""

TEMPLATE = """## 处罚决定书原文

{raw_text}

## 请抽取以下字段

{fields}

## 输出格式

{{
  "fields": {{
    "字段名": {{"value": 值或null, "quote": "原文片段或null"}}
  }}
}}"""

FIELD_SPECS = {
    "party_name": "当事人（企业或个人名称）",
    "penalty_authority": "作出处罚的机关全称",
    "publish_date": "处罚决定日期或公示日期，格式 YYYY-MM-DD",
    "doc_number": "处罚决定书文号，如「沪市监徐处〔2025〕012号」",
    "industry": "所属行业（如 保健食品 / 化妆品 / 游戏 / 医疗器械）",
    "product_or_service": "所涉商品或服务",
    "ad_channel": "广告发布渠道（如 抖音 / 微信公众号 / 电梯广告）",
    "illegal_claims": "违法宣称的具体表述，逐条列出，**照抄原文用语**",
    "legal_basis": "所依据的法律条款，逐条列出",
    "penalty_result": "处罚结果描述",
    "penalty_amount": "罚款金额（阿拉伯数字，单位元）",
    "facts_summary": "案件事实摘要",
    "regulatory_logic": "监管认定逻辑",
    "vector_text": "用于语义检索的自然语言场景描述",
    "keywords": "关键词，3-6 个",
}


def _norm(s: str) -> str:
    return _WS.sub("", s or "")


# 模型对列表字段常给「A……B……C」这种拼接引用：每段都是原文逐字，
# 合起来却不是原文里的任何一段。
_ELLIPSIS = re.compile(r"…+|\.{3,}")

# 拆出来的碎片至少要这么长才算数。短片段在长文里撞上纯属偶然，
# 放行等于把引用核对变成走过场 —— 那还不如不核。
_MIN_FRAGMENT = 4


def locate_quote(quote, flat_text: str) -> bool:
    """引用能否在原文定位。

    先整条核 —— 整条就是原文是最强的情形。核不上再按省略号拆开逐段核，
    **每段都必须命中**。实测 illegal_claims、product_or_service 就是被
    「整条核不上就判幻觉」误杀的：模型给的每一段都在原文里，只是它把
    几段拼在了一起。把正确的抽取结果当幻觉丢掉，比漏掉一次幻觉更糟 ——
    前者让字段静默变空，后者至少还有痕迹。
    """
    if quote in (None, "", [], {}):
        return False

    if isinstance(quote, (list, tuple)):
        parts = [_norm(str(q)) for q in quote]
    else:
        if _norm(str(quote)) in flat_text:
            return True
        parts = [_norm(p) for p in _ELLIPSIS.split(str(quote))]

    parts = [p for p in parts if p]
    if len(parts) < 2:
        return False  # 不是拼接引用，上面整条核过了，核不上就是核不上
    if any(len(p) < _MIN_FRAGMENT for p in parts):
        return False
    return all(p in flat_text for p in parts)


@dataclass
class ExtractionResult:
    fields: dict = field(default_factory=dict)
    quotes: dict = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    """因引用核对不上而被丢弃的字段。这个列表就是幻觉记录，要留痕。"""
    rule_extracted: dict = field(default_factory=dict)
    """由规则（正则）而非模型抽出的内容。

    要单独记：这部分逐字来自原文、可回原文定位，与模型给的可信度**不是一档**。
    人工复核时该先看哪些、能不能直接采信，靠的就是这个区分。
    """

    @property
    def hallucination_rate(self) -> float:
        total = len(self.fields) + len(self.dropped)
        return len(self.dropped) / total if total else 0.0


# ── 总局典型案例通报（一篇文章=多起案例）的规则抽取 ──────────────
# mock 模式没有 LLM 可用；总局典型案正文句式高度规整，正则即可抽出
# 当事人/机关/金额/法条/宣称，且每一条都逐字来自原文、可回原文定位。
# 规则层抽不到只留空，绝不推测 —— 与 LLM 路径的引用核对是同一原则。

_SAMR_TITLE = re.compile(r"^[ \t]*(?:[一二三四五六七八九十百]+[、．.]|案例[一二三四五六七八九十百]+[：:])\s*(?P<title>[^\n]{4,90})")
_SAMR_AUTHORITY = re.compile(
    r"(?P<a>[^，。\s]{2,30}?(?:市场监督管理综合行政执法总队|市场监管综合行政执法总队|市场监督管理局|"
    r"市场监督管理分局|监督管理局|工商(?:行政)?管理局|监管局))\s*(?:将依据|将根据|将责令|将作出|依据|根据|依照|责令|对当事人|作出|已依法|接到)"
)
_SAMR_PARTY = re.compile(
    r"(?:对|查处|反映|举报|经查|当事人)[，,:：]?\s*(?P<p>[^，。：\s对依据]{2,40}?(?:食品店|专卖店|商店|药店|门诊部|超市|商行|"
    r"有限公司|有限责任公司|股份有限公司|公司|经营部|服务中心|医院|集团|厂|合作社|工作室|分公司))"
)
_SAMR_AMOUNT = re.compile(r"(?:罚款|罚没款)(?:人民币)?\s*(?P<num>[\d,，]+(?:[.]\d+)?)\s*(?P<unit>万元|元整|元)")
_SAMR_RESULT = re.compile(r"[^。；]*?(?:责令[^。；]*?|处以罚款[^。；]*?|处罚款[^。；]*?|罚没款[^。；]*?|作出[^。；]{0,40}?行政处罚[^。；]*?)[。；]?")
_SAMR_QUOTE = re.compile(r"[“「](?P<q>[^”」]{2,80})[”」]")
_SAMR_THIS_CASE = re.compile(r"本案(?!情)[^。]{0,120}。")
_SAMR_TITLE_INLINE = re.compile(r"查处(?P<t>[^。；\n]{4,80}?案)")
_SAMR_ENTITY = re.compile(
    r"(?P<p>[^，。：\s]{2,40}?(?:食品店|专卖店|商店|药店|门诊部|超市|商行|"
    r"有限公司|有限责任公司|股份有限公司|公司|经营部|服务中心|医院|集团|厂|合作社|工作室|分公司))"
)


# 总局通报每个案子的正文段大多 200-400 字；留足余量，仍设上限防止
# 异常长段把单条 chunk 撑爆。截断必须落在句界上，绝不切在半句中间。
_MAX_FACTS_CHARS = 600
_MAX_VECTOR_CHARS = 400
_SENTENCE_END = "。；！？"


def _segment_body(t: str) -> str:
    """小节标题行之后的正文，逐字拼回（页面常把一句话硬折成多行）。"""
    body = (t or "").strip()
    m = _SAMR_TITLE.match(body)
    if m:
        body = body[m.end():]
    else:
        # 标题与正文挤在同一行时（inline 标题正则那一路），只去前缀标题
        mi = re.match(r"\s*查处.+?案[\s，,：:]*", body)
        if mi:
            body = body[mi.end():]
    return "".join(line.strip() for line in body.splitlines() if line.strip()).strip()


def _cap_sentence(s: str, limit: int) -> str:
    """超长时在最近的句末标点处收束；前半段连句界都没有才硬截。"""
    if len(s) <= limit:
        return s
    window = s[:limit]
    cut = max(window.rfind("。"), window.rfind("；"),
              window.rfind("！"), window.rfind("？"))
    return window[: cut + 1] if cut >= limit // 2 else window


_RISK_MAP = [
    (("医", "药", "制药"), ["医疗广告违规", "虚假宣传", "医疗用语"]),
    (("房地产", "楼盘", "房"), ["房地产广告误导", "升值承诺", "虚假宣传"]),
    (("保健", "健康", "食品", "奶粉", "益生菌", "营养"), ["保健食品违规宣传", "虚假宣传", "功效无依据"]),
    (("化妆", "面膜", "精华"), ["化妆品虚假宣传", "虚假宣传"]),
    (("游戏", "手游", "充值", "抽卡"), ["游戏广告允诺不清楚", "虚假宣传"]),
    (("直播", "带货", "电商", "网店", "平台"), ["直播带货违法广告", "虚假宣传", "广告内容真实性"]),
]


def _risk_dimensions_of(text: str, industry: str = "") -> list[str]:
    for kws, risks in _RISK_MAP:
        if any(k in text for k in kws) or any(k in industry for k in kws):
            return list(risks)
    return ["虚假宣传", "广告内容真实性"]


def _industry_of(text: str) -> str:
    for kw, ind in (("化妆品", "化妆品"), ("医疗器械", "医疗器械"), ("医美", "医疗"),
                    ("药品", "医疗"), ("医疗", "医疗"), ("游戏", "游戏")):
        if kw in text:
            return ind
    if any(k in text for k in ("食品", "奶粉", "益生菌", "蛋白", "营养", "养生", "保健", "特医")):
        return "保健食品"
    return "通用"


def rule_extract_samr_typical(raw_text: str) -> dict:
    """从总局典型案正文段抽结构化字段（逐字来自原文）。"""
    out: dict = {}
    t = raw_text or ""

    m = _SAMR_TITLE.search(t)
    if m:
        out["title"] = m.group("title").strip()
    else:
        mi = _SAMR_TITLE_INLINE.search(t)
        if mi:
            out["title"] = mi.group("t").strip()

    am = _SAMR_AUTHORITY.search(t)
    if am:
        out["penalty_authority"] = am.group("a").strip()

    pm = _SAMR_PARTY.search(t)
    if not pm:
        pm = _SAMR_ENTITY.search(t)
    if pm:
        party = pm.group("p").strip()
        party = re.sub(r"^(?:案情介绍|案例[一二三四五六七八九十]+|[：:])[：:]?", "", party).strip()
        party = re.sub(r"^(?:反映|查处|举报|经查|当事人|对)[，,:：]?", "", party).strip()
        out["party_name"] = party

    money = _SAMR_AMOUNT.search(t)
    if money:
        num = float(money.group("num").replace(",", "").replace("，", ""))
        out["penalty_amount"] = int(num * 10000) if money.group("unit") == "万元" else int(num)

    rm = _SAMR_RESULT.search(t)
    if rm:
        out["penalty_result"] = rm.group(0).strip()

    quotes = []
    for q in _SAMR_QUOTE.findall(t):
        q = q.strip()
        if q and q not in quotes:
            quotes.append(q)
    if quotes:
        out["illegal_claims"] = quotes

    from app.crawler.legalref import legal_basis_from_text, find_law_mentions
    basis = legal_basis_from_text(t)
    if basis:
        out["legal_basis"] = basis
    mentions = list(find_law_mentions(t))
    if mentions:
        out["legal_basis_inferred"] = mentions

    out["industry"] = _industry_of(t)
    out["risk_dimensions"] = _risk_dimensions_of(t, out.get("industry", ""))

    # 事实/监管逻辑/检索描述：一律用原文片段拼接，不新造句子。
    # body 是去掉小节标题行后的整段正文（经查事实 + 处罚结果），逐字来自原文；
    # 早年这里写成 t[:80]，80 字往往连第一句「经查……」都没结束，
    # 案情在半句上被硬切断（实测 42 条中招，末尾停在半个英文商品名上）。
    body = _segment_body(t)
    tc = _SAMR_THIS_CASE.search(t)
    out["facts_summary"] = _cap_sentence(body, _MAX_FACTS_CHARS)
    if tc:
        out["regulatory_logic"] = tc.group(0).strip()
    elif out.get("penalty_result"):
        out["regulatory_logic"] = out["penalty_result"]
    elif body:
        # 通报常把认定逻辑落在末句（处罚决定），抽不到专门句式时退回末句
        out["regulatory_logic"] = body[max(0, len(body) - 160):]
    claims_txt = "；".join(quotes[:5])
    out["vector_text"] = (
        f"这是一起市场监管部门查处的广告违法案例。{_cap_sentence(body, _MAX_VECTOR_CHARS)}"
        + (f"涉案广告宣称：{claims_txt}。" if claims_txt else "")
        + (f"处理结果：{out.get('penalty_result', '')}" if out.get("penalty_result") else "")
    )
    out["keywords"] = (quotes[:3] + ([out.get("penalty_authority", "")] if out.get("penalty_authority") else []))[:6]
    return out


class Extractor:

    """结构化抽取器。

    ⚠️ 它只负责抽取，不判断案例是否可信 —— 那是 quality.validate_case 的活。
    """

    def __init__(self, llm, max_chars: int = 12000):
        self.llm = llm
        self.max_chars = max_chars

    def build_prompt(self, raw_text: str) -> str:
        fields = "\n".join(f"- {k}：{v}" for k, v in FIELD_SPECS.items())
        return TEMPLATE.format(raw_text=raw_text[: self.max_chars], fields=fields)

    def extract(self, raw_text: str) -> ExtractionResult:
        # 规则层打底：总局典型案正文段可直接用正则抽，逐字来自原文
        res = self._extract_by_rules(raw_text)

        # mock 不做推理，直接返回规则层结果（规则层已保证可回原文定位）
        if getattr(self.llm, "name", "") == "mock":
            return res

        try:
            raw = self.llm.complete(SYSTEM, self.build_prompt(raw_text))
            m = _JSON.search(raw or "")
            if not m:
                raise ValueError(f"模型回包里找不到 JSON：{(raw or '')[:200]}")
            data = json.loads(m.group())
            llm_res = self._verify(data.get("fields") or {}, raw_text)
            # 模型字段只补规则层没抽到或抽空的，避免覆盖逐字原文结果
            for k, v in llm_res.fields.items():
                if k not in res.fields or not res.fields.get(k):
                    res.fields[k] = v
                    if k in llm_res.quotes:
                        res.quotes[k] = llm_res.quotes[k]
            if llm_res.dropped:
                res.dropped = llm_res.dropped
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM 抽取失败，保留规则层结果：%s", str(exc)[:120])
        self._apply_rules(res, raw_text)
        return res

    @staticmethod
    def _extract_by_rules(raw_text: str) -> ExtractionResult:
        res = ExtractionResult()
        fields = rule_extract_samr_typical(raw_text)
        for k, v in fields.items():
            if k == "legal_basis_inferred":
                res.fields["legal_basis_inferred"] = v
            else:
                res.fields[k] = v
                res.rule_extracted[k] = v
        return res

    @staticmethod
    def _apply_rules(res: ExtractionResult, raw_text: str) -> None:
        """规则层：能用正则从原文直接抽的，不交给模型定夺。

        目前只有 legal_basis。它原先只有模型这一条路，实测 30 条案例丢了 14 条，
        抽检发现丢的多数不是「核对不上」而是「模型没抽」—— 段落里明写着
        「违反了《中华人民共和国反不正当竞争法》第九条第一款的规定」，模型给 null。
        正则抽的每一条按构造就是原文逐字，抽不到只是抽不到，不会抽错。
        """
        from app.crawler.legalref import merge_legal_basis

        model_val = res.fields.get("legal_basis")
        if isinstance(model_val, str):
            model_val = [model_val]
        lb = merge_legal_basis(model_val, raw_text)

        if lb.inferred:
            # 不丢，但也绝不留在 legal_basis 里：总局通报大量写「依据《广告法》
            # 有关规定」不给条号，模型几乎必然补出一个条号 —— 那个条号在法律上
            # 可能是对的，但**原文没有这句话**，法务照着去核会核不到。
            res.fields["legal_basis_inferred"] = lb.inferred
            logger.info("模型给的 %d 条法条原文无条号支撑，已移入 legal_basis_inferred：%s",
                        len(lb.inferred), lb.inferred)

        if lb.basis:
            res.fields["legal_basis"] = lb.basis
            rule_part = [b for b in lb.basis if b not in (model_val or [])]
            if rule_part:
                res.rule_extracted["legal_basis"] = rule_part
                # 模型漏抽而正则补上的，不该继续算在「幻觉丢弃」里 —— 那是两回事
                if "legal_basis" in res.dropped:
                    res.dropped.remove("legal_basis")
                    logger.info("legal_basis 由正则从原文补出 %d 条", len(rule_part))
        elif "legal_basis" in res.fields:
            # 模型给的全是推断，原文一条也支撑不了 —— 必须清空。
            # ⚠️ 这一支是引用核对拦不住的：模型照抄「依据《广告法》有关规定」
            # 当 quote，那句话确实在原文里，却支撑不了它给的条号。
            # 只把推断另存一份而把原值留在 legal_basis，等于什么都没防住。
            res.fields.pop("legal_basis")
            res.quotes.pop("legal_basis", None)

    def _verify(self, fields: dict, raw_text: str) -> ExtractionResult:
        """逐字段核对引用。核不上就丢弃。"""
        flat = _norm(raw_text)
        res = ExtractionResult()

        for name, item in fields.items():
            if not isinstance(item, dict):
                continue
            value, quote = item.get("value"), item.get("quote")
            if value in (None, "", [], {}):
                continue

            # 纯检索辅助字段：编错只影响召回质量，不影响法律结论，不要求出处
            if name in FREE_FIELDS:
                res.fields[name] = value
                if quote:
                    res.quotes[name] = quote
                continue

            # 叙述类字段是概括，不要求逐字出现；但仍要求给出依据段落，
            # 一个字都引不出来说明模型没在读原文。
            if name in NARRATIVE_FIELDS:
                if not quote:
                    res.dropped.append(name)
                    logger.warning("字段 %s 未提供依据段落，丢弃", name)
                    continue
                res.fields[name] = value
                res.quotes[name] = quote
                continue

            located = locate_quote(quote, flat)
            if not located:
                res.dropped.append(name)
                logger.warning(
                    "字段 %s 的引用在原文中找不到，判定为幻觉并丢弃：%r",
                    name, str(quote)[:60],
                )
                continue

            res.fields[name] = value
            res.quotes[name] = quote

        # 关键字段必须有引用支撑，缺一个都不行
        for name in CRITICAL_FIELDS:
            if name in res.fields and name not in res.quotes:
                res.fields.pop(name)
                res.dropped.append(name)

        if res.dropped:
            logger.info("抽取完成，丢弃 %d 个无原文支撑的字段：%s",
                        len(res.dropped), res.dropped)
        return res


def to_case(result: ExtractionResult, case_id: str, source_url: str,
            raw_text_path: str, source_name: str = "") -> dict:
    """把抽取结果组装成案例库 schema。

    ⚠️ 当事人姓名在这里脱敏 —— 越早越好，别让原始姓名流到下游。
    """
    from app.crawler.policy import desensitize_party

    # Keep the root repository's case contract stable even when extraction
    # cannot support a field.  Unknown values stay empty and are routed to
    # human review; they are never guessed merely to satisfy the schema.
    c = {
        "title": "",
        "publish_date": "",
        "penalty_authority": "",
        "party_name": "",
        "industry": "",
        "product_or_service": "",
        "ad_channel": "",
        "risk_dimensions": [],
        "illegal_claims": [],
        "facts_summary": "",
        "legal_basis": [],
        "penalty_result": "",
        "penalty_amount": None,
        "regulatory_logic": "",
        "mapped_rule_ids": [],
        "keywords": [],
        "vector_text": "",
    }
    c.update(result.fields)
    c.update({
        "case_id": case_id,
        "source_type": "automated_official_crawl_pending_human_review",
        "source_url": source_url,
        "raw_text_path": raw_text_path,
        "source_name": source_name,
        "review_status": "pending_review",
        "approved_for_rag": False,
        "human_review_required": True,
        "extraction_quotes": result.quotes,
        "extraction_dropped": result.dropped,
        "rule_extracted": result.rule_extracted,
    })
    if c.get("party_name"):
        c["party_name"] = desensitize_party(str(c["party_name"]))
    for k in ("illegal_claims", "legal_basis", "keywords", "risk_dimensions"):
        v = c.get(k)
        if isinstance(v, str):
            c[k] = [v]
        elif v is None:
            c[k] = []
    return c
