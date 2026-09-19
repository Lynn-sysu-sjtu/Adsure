"""质量门禁与去重。

抓回来的东西**不能直接信**。这一层逐项过关，不过关的按严重程度分三种处理：

    reject  拒收 —— 缺了它这条案例就没有价值（如没有出处）
    repair  清掉存疑字段后收 —— 字段不可信，但案例本身有价值
    flag    标记后收 —— 可能是我们的规则库不全，不是案例的错

设计原则：**能修的修，修不了的标记，出处缺失的直接拒**。
不提供「跳过校验」的开关 —— 理由同 robots 门禁：留了就会被打开。
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


class Severity(StrEnum):
    REJECT = "reject"
    REPAIR = "repair"
    FLAG = "flag"


@dataclass
class Issue:
    field: str
    severity: Severity
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.field}: {self.message}"


@dataclass
class ValidationResult:
    case: dict
    issues: list[Issue] = field(default_factory=list)

    @property
    def rejected(self) -> bool:
        return any(i.severity is Severity.REJECT for i in self.issues)

    @property
    def flags(self) -> list[str]:
        return [i.field for i in self.issues if i.severity is not Severity.REJECT]

    def add(self, fld: str, sev: Severity, msg: str) -> None:
        self.issues.append(Issue(fld, sev, msg))


# ══════════════════════════════════════════════════════════════
#  金额核对
# ══════════════════════════════════════════════════════════════

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def amount_renderings(amount: float) -> list[str]:
    """一个金额在处罚决定书里可能的几种写法。

    抽取出 600000 却在原文里搜 "600000"，多半搜不到 ——
    决定书通常写「六十万元」或「60万元」。只搜一种写法会把
    正确的抽取结果误判成幻觉，那比不校验还糟。
    """
    out: list[str] = []
    n = int(amount)
    out += [str(n), f"{n:,}", f"{n}元"]

    # ⚠️ 「万」形式**不能只对整万数生成**。
    # 实测踩到：原文写「罚款8.33万元」，模型正确抽出 83300，
    # 但当时只在 n%10000==0 或 n%1000==0 时才生成万形式，
    # 83300 两个条件都不满足 → 核不上 → 正确的抽取结果被当成幻觉清空。
    # 这正是本函数注释里警告过的那种错误，却在非整万金额上重犯了一次。
    if n >= 10_000:
        w = f"{n / 10_000:g}"
        out += [f"{w}万", f"{w}万元"]
    if n >= 100_000_000:
        y = f"{n / 100_000_000:g}"
        out += [f"{y}亿", f"{y}亿元"]
    return out


def verify_amount(amount: float | None, raw_text: str) -> bool:
    """金额能否在原文中找到。找不到即视为不可信。"""
    if amount is None or not raw_text:
        return False
    flat = re.sub(r"[\s,，]", "", raw_text)
    return any(re.sub(r"[\s,，]", "", r) in flat for r in amount_renderings(amount))


# ══════════════════════════════════════════════════════════════
#  vector_text 质量
# ══════════════════════════════════════════════════════════════

_PUNCT = re.compile(r"[，。；、：,.;:]")


def looks_like_keyword_soup(text: str) -> bool:
    """判断 vector_text 是不是关键词堆砌。

    AGENTS.md 明确要求它必须是自然语言场景描述 —— 因为它是 RAG 的检索载体，
    堆关键词会让语义检索退化成关键词匹配，把向量库的意义抹掉。
    """
    t = (text or "").strip()
    if len(t) < 40:
        return True
    # 顿号密度过高 = 在列举而不是在叙述
    if t.count("、") >= 6 and len(_PUNCT.sub("", t)) / max(t.count("、"), 1) < 8:
        return True
    # 完全没有句读，不像句子
    if not _PUNCT.search(t):
        return True
    return False


# ══════════════════════════════════════════════════════════════
#  校验
# ══════════════════════════════════════════════════════════════

REQUIRED_FOR_LANDING = ("case_id", "source_url", "raw_text_path")

# 文章结构小标题，不是案子名。取自实际抓到的叙事式通报。
_NON_CASE_HEADING = re.compile(
    r"^(案情回顾|案件回顾|案例回顾|联合执法|协同(?:作战|治理)|工作成效|查处经过"
    r"|温馨提醒|消费提示|风险提示|下一步|下步|结语|背景(?:情况|介绍)"
    r"|专家点评|典型意义|案例评析|编者按)"
)


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def validate_case(
    case: dict,
    raw_text: str = "",
    known_rule_ids: set[str] | None = None,
    today: date | None = None,
) -> ValidationResult:
    """质量门禁。返回带 issues 的结果，调用方据此决定收不收。"""
    res = ValidationResult(case=dict(case))
    c = res.case
    today = today or date.today()

    # ── 出处：缺了就没有价值，直接拒 ──
    for fld in REQUIRED_FOR_LANDING:
        if not (c.get(fld) or "").strip() if isinstance(c.get(fld), str) else not c.get(fld):
            res.add(fld, Severity.REJECT,
                    "缺失。没有出处的案例无法在报告中引用 —— "
                    "法务追问「哪个案子、哪里能看到」时答不上来，等于没有价值。")

    if not raw_text.strip():
        res.add("raw_text", Severity.REJECT, "原文为空，无法核对任何抽取结果")

    # ── 这到底是不是一个案例 ──
    # 总局有些通报是**叙事式新闻稿**，小节标题是「案情回顾 / 联合执法 / 温馨提醒」，
    # 按典型案例通报的规则切段就会把这些小节当成案例。实测入库 111 条里混进 4 条。
    # 它们进了 RAG 会被当成真实案例检索出来 —— 比少 4 条案例糟得多。
    title = (c.get("segment_title") or c.get("title") or "").strip()
    if _NON_CASE_HEADING.match(title):
        res.add("segment_title", Severity.REJECT,
                f"「{title[:20]}」是文章结构小标题，不是案例。"
                "这类通报是叙事式新闻稿，不该按典型案例通报切段。")
    elif not _text(c.get("party_name")) and not _text(c.get("penalty_authority")):
        # 单独缺一个是抽取失败（案例仍可用），两个都缺则连「谁被谁罚了」都答不出，
        # 在报告里引用不了 —— 与 source_url 缺失同理。
        res.add("party_name", Severity.REJECT,
                "既无当事人也无处罚机关。报告里写「该表述在 XX 案中被认定为违规」时，"
                "答不出是哪个案子、谁认定的 —— 多半根本不是一个案例。")

    # ── 金额：核不上就清掉，不拒收 ──
    amt = c.get("penalty_amount")
    if amt is not None and raw_text and not verify_amount(amt, raw_text):
        res.add("penalty_amount", Severity.REPAIR,
                f"抽取值 {amt} 在原文中找不到对应写法，已清空。"
                "报告里引用一个不存在的罚款金额，比不引用糟糕得多。")
        c["penalty_amount"] = None

    # ── 法条：找不到多半是我们的规则目录不全，标记不拒 ──
    if known_rule_ids is not None:
        unmapped = [r for r in (c.get("mapped_rule_ids") or []) if r not in known_rule_ids]
        if unmapped:
            res.add("mapped_rule_ids", Severity.FLAG,
                    f"规则目录中不存在：{unmapped}。"
                    "可能是目录缺条（如已知缺 ADLAW-008），非案例问题。")

    # ── 法条：没有法条的案例做不了规则 RAG，但仍可能有事实价值 ──
    if not (c.get("legal_basis") or []):
        res.add("legal_basis", Severity.FLAG,
                "未抽出法律依据。该案例无法用于规则 RAG（类案检索按法条关联），"
                "但事实本身仍可能有参考价值，交人工判断是否保留。")

    # ── 模型推断出的条号：不拒、不采信，交人工定夺 ──
    # 总局典型案例通报大量写「依据《广告法》有关规定」而不给条号，模型几乎必然
    # 补出一个 —— 那个条号在法律上多半是对的，但原文里没有这句话。
    # 它有参考价值（懂法的人一看就知道对不对），但不能当抽取结果用。
    if c.get("legal_basis_inferred"):
        res.add("legal_basis_inferred", Severity.FLAG,
                f"模型给出的条号 {c['legal_basis_inferred']} 在原文中无条号支撑，"
                "已隔离、不计入法律依据。原文只写到法规一级。"
                "需要精确到条款时，须由人回原文或去查处罚决定书原件确认。")

    # ── 日期合理性 ──
    pub = (c.get("publish_date") or "").strip()
    if pub:
        try:
            d = datetime.strptime(pub[:10], "%Y-%m-%d").date()
            if d > today:
                res.add("publish_date", Severity.FLAG, f"日期 {pub} 在未来，需人工核")
        except ValueError:
            res.add("publish_date", Severity.FLAG, f"日期格式无法解析：{pub!r}")

    # ── vector_text ──
    if looks_like_keyword_soup(c.get("vector_text") or ""):
        res.add("vector_text", Severity.REPAIR,
                "不是自然语言场景描述（过短或关键词堆砌），已清空待重抽。"
                "它是 RAG 的检索载体，堆关键词会让语义检索退化。")
        c["vector_text"] = ""

    # ── 入库状态：抓来的一律待复核，不给自动放行的余地 ──
    if c.get("review_status") == "approved":
        res.add("review_status", Severity.REPAIR,
                "抓取产出不得自带 approved，已改为 pending_review。"
                "两级入库的意义就在于人必须在环。")
    c["review_status"] = "pending_review"

    return res


# ══════════════════════════════════════════════════════════════
#  去重
# ══════════════════════════════════════════════════════════════

_DOC_NO = re.compile(r"[〔\[（(]\s*\d{4}\s*[〕\])）]\s*第?\s*[\dA-Za-z\-]+\s*号")


def extract_doc_number(text: str) -> str | None:
    """从原文里抠处罚决定书文号，如「沪市监徐处〔2025〕012 号」。

    文号是最可靠的指纹：同一份决定书在不同网站转载，文号是一样的。
    """
    if not text:
        return None
    m = _DOC_NO.search(text)
    if not m:
        return None
    start = max(0, m.start() - 20)
    seg = text[start:m.end()]
    seg = re.sub(r"^.*?([一-鿿]{2,}[〔\[（(])", r"\1", seg)
    return re.sub(r"\s+", "", seg)


def fingerprint(case: dict, raw_text: str = "") -> tuple[str, str]:
    """返回 (指纹, 采用的口径)。口径要一起返回 —— 排查重复误判时，
    知道是靠哪一级判出来的比指纹本身有用。"""
    doc_no = case.get("doc_number") or extract_doc_number(raw_text)
    if doc_no:
        return _h(doc_no), "文号"

    authority = (case.get("penalty_authority") or "").strip()
    party = (case.get("party_name") or "").strip()
    pub = (case.get("publish_date") or "").strip()[:10]
    if authority and party and pub:
        return _h(f"{authority}|{party}|{pub}"), "机关+当事人+日期"

    amt = case.get("penalty_amount")
    facts = re.sub(r"\s+", "", (case.get("facts_summary") or ""))[:50]
    if party and facts:
        return _h(f"{party}|{amt}|{facts}"), "当事人+金额+事实摘要"

    return _h(case.get("case_id") or repr(case)), "兜底(case_id)"


def _h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


@dataclass
class DedupIndex:
    """指纹索引。同一案子多源出现时保留优先级更高的源，其余记入 also_seen_at。

    多源印证本身是可信度信号，所以不丢弃，只是不重复入库。
    """

    _seen: dict[str, dict] = field(default_factory=dict)

    def add_existing(self, case: dict, raw_text: str = "") -> None:
        fp, _ = fingerprint(case, raw_text)
        self._seen.setdefault(fp, case)

    def check(self, case: dict, raw_text: str = "") -> tuple[bool, dict | None, str]:
        """返回 (是否重复, 已有案例, 指纹口径)。"""
        fp, basis = fingerprint(case, raw_text)
        existing = self._seen.get(fp)
        if existing is None:
            self._seen[fp] = case
            return False, None, basis
        return True, existing, basis

    def merge_source(self, existing: dict, new_case: dict) -> dict:
        """把新源记进 also_seen_at，不覆盖主记录。"""
        url = new_case.get("source_url")
        if not url:
            return existing
        seen = existing.setdefault("also_seen_at", [])
        if url not in seen:
            seen.append(url)
        return existing
