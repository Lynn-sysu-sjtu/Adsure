"""法条引用抽取 —— 用正则，不用模型。

`extract.py` 的原则是「规则优先，大模型兜底」，但 legal_basis 一直只有模型这一条路，
实测 30 条案例里丢了 14 条。抽检发现丢的不是「核对不上」而是「模型没抽」：
段落里明写着「违反了《中华人民共和国反不正当竞争法》第九条第一款的规定」，
模型却给了 null。

法条引用是**固定句式**，正则抽出来的每一条按构造就是原文逐字，
不存在幻觉的可能 —— 这比「让模型抽再回原文核对」严格更强：

    模型抽 + 核对 ：抽错了能发现，抽漏了发现不了
    正则抽        ：抽漏了能补，抽错了不可能

所以这里不是给模型「兜底」，是反过来 —— 正则打底，模型补它够不着的部分
（如原文写「上述行为违反广告法相关规定」这种不带条号的表述）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)

_CN_NUM = "一二三四五六七八九十百零〇两"

# 「第X条」及其常见后缀：第九条第一款、第二十八条第二款第（三）项、第十条之一
_ARTICLE = (
    rf"第[{_CN_NUM}\d]{{1,10}}条"
    rf"(?:之[{_CN_NUM}\d]{{1,3}})?"
    rf"(?:第[{_CN_NUM}\d]{{1,6}}款)?"
    rf"(?:第[（(][{_CN_NUM}\d]{{1,6}}[)）]项)?"
)

# 《法规名》后面**必须**跟条号才算引用。
# 这一条同时挡掉了文书名、证书名、标准名 ——《宝玉石及贵金属饰品鉴定证书》
# 后面不会跟「第N条」，自然不会被当成法律依据。
_CITATION = re.compile(
    rf"《(?P<law>[^》《\n]{{2,40}})》\s*"
    rf"(?P<first>{_ARTICLE})"
    rf"(?P<more>(?:\s*[、,，]?\s*(?:和|以及|及)?\s*{_ARTICLE})*)"
)
_ARTICLE_RE = re.compile(_ARTICLE)

# 认定语境：往前看一小段，判断这条是「被违反的规范」还是「处罚所依据的规范」。
# 这个区分对类案检索有实际价值 —— 按「违反了哪一条」关联比按「依据哪一条罚」准得多。
_VIOLATED = re.compile(r"违反|不符合|违背")
_PENALTY = re.compile(r"依据|根据|依照|按照")
_LOOKBACK = 40


class BasisKind(StrEnum):
    VIOLATED = "violated"       # 被违反的规范
    PENALTY = "penalty"         # 处罚所依据的规范
    UNMARKED = "unmarked"       # 语境不明，不猜


@dataclass(frozen=True)
class LegalCitation:
    law: str
    article: str
    kind: BasisKind
    quote: str
    """原文中的完整匹配片段。它就是这条引用的出处，可直接回原文定位。"""

    @property
    def text(self) -> str:
        return f"《{self.law}》{self.article}"


def _kind_of(text: str, at: int) -> BasisKind:
    """看引用前面那一小段是「违反」还是「依据」。

    只往前看 40 字并在句读处截断 —— 跨句去猜语境会把上一案的表述算到这一条头上。
    """
    head = text[max(0, at - _LOOKBACK): at]
    head = re.split(r"[。；;\n]", head)[-1]
    if _VIOLATED.search(head):
        return BasisKind.VIOLATED
    if _PENALTY.search(head):
        return BasisKind.PENALTY
    return BasisKind.UNMARKED


def find_citations(text: str) -> list[LegalCitation]:
    """抽出原文里所有「《法规名》第N条」形式的引用，按出现顺序、去重。

    一处引用多条（「第四条第一款、第二十八条第二款」）会展开成多条，
    每条都挂同一个 law —— 规则 RAG 是按「法条」检索的，不是按「引用句」。
    """
    out: list[LegalCitation] = []
    seen: set[tuple[str, str]] = set()

    for m in _CITATION.finditer(text or ""):
        law = re.sub(r"\s+", "", m.group("law"))
        kind = _kind_of(text, m.start())
        arts = [m.group("first")] + _ARTICLE_RE.findall(m.group("more") or "")
        for art in arts:
            art = re.sub(r"\s+", "", art)
            key = (law, art)
            if key in seen:
                continue
            seen.add(key)
            out.append(LegalCitation(law=law, article=art, kind=kind,
                                     quote=re.sub(r"\s+", "", m.group())))
    return out


def legal_basis_from_text(text: str) -> list[str]:
    """给案例库用的扁平列表，如 ["《中华人民共和国广告法》第十七条"]。"""
    return [c.text for c in find_citations(text)]


_ABBREV = re.compile(r"中华人民共和国|中国|暂行|试行|[\s　]")
_LAW_NAME = re.compile(r"《(?P<law>[^》《\n]{2,40}(?:法|条例|办法|规定|规则|准则|指南))》")
_LAW_SUFFIX = re.compile(r"^\s*(?:的?有关|的?相关|等)?规定")


def _dedup_key(s: str) -> str:
    """比对用的归一化写法。

    模型常把原文的《广告法》补全成《中华人民共和国广告法》—— 同一条法条的
    两种写法，去重时要认作一条，**留下正则抽的那个原文写法**（可回原文定位）。
    """
    return _ABBREV.sub("", s or "")


def _law_key(s: str) -> str:
    """只取法规名部分做比对，丢掉条号。"""
    m = re.match(r"\s*《([^》]+)》", s or "")
    return _dedup_key(m.group(1)) if m else ""


def find_law_mentions(text: str) -> list[str]:
    """只提到法规名、不带条号的援引。

    总局典型案例通报的常见写法就是这种：
        「邳州市市场监管局依据《中华人民共和国广告法》有关规定，对当事人作出…」
    没有条号。它是**真实的**法律依据，只是精度到法规一级，
    与「第十七条」不是一回事，必须分开记。
    """
    out, seen = [], set()
    for m in _LAW_NAME.finditer(text or ""):
        tail = text[m.end(): m.end() + 12]
        if _ARTICLE_RE.match(tail.lstrip()):
            continue  # 后面跟着条号，归 find_citations 管
        law = re.sub(r"\s+", "", m.group("law"))
        k = _dedup_key(law)
        if k in seen:
            continue
        seen.add(k)
        out.append(f"《{law}》")
    return out


@dataclass
class LegalBasis:
    """法律依据的三档，按**可信度**分，不按内容分。

    这个区分不是洁癖：总局通报里「依据《广告法》有关规定」占了很大比例，
    而模型面对「宣称改善骨关节、杀灭幽门螺旋杆菌」几乎必然补出「第十七条」——
    那个推断在法律上多半是对的，但**原文没有这句话**。
    把它混进 legal_basis，报告里就会出现一个原文并不支持的条号，
    法务照着去核会核不到。AGENTS.md 的红线正是「不得编造法律依据」。
    """

    citations: list[str]
    """条款级，逐字来自原文（《X》第N条）。可直接采信。"""
    laws: list[str]
    """法规级，原文只写到法规名。真实但精度只到这一级。"""
    inferred: list[str]
    """模型给了条号、原文却查不到该法任何条号 —— 是推断，不是抽取。"""

    @property
    def basis(self) -> list[str]:
        """可作为「法律依据」写进案例的部分。推断不在其中。"""
        return self.citations + self.laws


def merge_legal_basis(model_values: list[str] | None, text: str) -> LegalBasis:
    """合并模型抽取与正则抽取，并把「推断」摘出去。

    规则：
      1. 正则抽到的条款级引用最可信，排最前，同一条以原文写法为准；
      2. 模型给的条号，只有当原文里该法**确实出现过条号**时才采信 ——
         原文写「依据《广告法》有关规定」而模型给「第十七条」，是推断；
      3. 原文只到法规名的，如实记到法规级，不向上编，也不向下删。
    """
    citations = legal_basis_from_text(text)
    cited_laws = {_law_key(c) for c in citations}
    laws = [l for l in find_law_mentions(text) if _law_key(l) not in cited_laws]

    seen = {_dedup_key(v) for v in citations} | {_dedup_key(v) for v in laws}
    inferred: list[str] = []

    for v in model_values or []:
        v = str(v)
        k = _dedup_key(v)
        if not k or k in seen:
            continue
        seen.add(k)
        # 模型给了条号，但原文里这部法规一个条号都没出现过 → 推断
        if _ARTICLE_RE.search(v) and _law_key(v) not in cited_laws:
            inferred.append(v)
        else:
            citations.append(v)

    return LegalBasis(citations=citations, laws=laws, inferred=inferred)
