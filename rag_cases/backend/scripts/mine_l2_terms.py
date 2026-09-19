# -*- coding: utf-8 -*-
"""从行政处罚案例库挖掘 L2 行业禁用语候选。

**这个脚本产出的是人工复核工作表，不是可以直接上线的词库。**

原因：案例里的 illegal_claims 字段混着三类内容，机器分不干净——
    真违规宣称   「清除血液垃圾斑块」「有效预防近视」
    产品名       「三七人参胶囊」「奇宇牌钙咀嚼片」「欣方」
    无害描述     「补充钙」
把「欣方」这种品牌名放进词库会命中一切素材。所以这里只做两件事：

  ① 频次挖掘 —— 找出跨案例反复出现的短片段，**包括我没想到的说法**
  ② 挂上出处 —— 每个候选词都带上真实案号、行业、处罚金额

最后由人判断哪些进词库。这一步省不掉，也不该省。

用法：
    python backend/scripts/mine_l2_terms.py
输出：
    docs/L2_candidates_review.md    人工复核工作表
    docs/L2_draft.yaml              草稿词库（reviewed_by_legal: false）
"""

from __future__ import annotations

import collections
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs"

# 赛道归并：案例库里的 industry 字段写法不统一，先归一
SECTOR_PATTERNS = {
    "health_food": ["保健食品", "保健品", "普通食品", "健康产品", "食品"],
    "cosmetics": ["化妆品", "美妆", "医疗美容", "医美"],
    "game": ["游戏"],
}

# 功效动词种子：这些是 L2 的核心信号词，命中即高度可疑
EFFICACY_VERBS = [
    "治疗", "治愈", "根治", "痊愈", "康复", "医治", "疗效",
    "预防", "防治", "抗癌", "抑制", "消除", "清除", "排出", "排毒",
    "缓解", "改善", "修复", "再生", "增强", "提高免疫", "调理", "滋补",
    "祛痘", "祛斑", "祛皱", "去皱", "美白", "淡斑", "生发", "脱发",
    "降血压", "降血脂", "降血糖", "减肥", "瘦身", "丰胸",
]

# 疾病与症状种子：非医疗类广告出现即触及《广告法》第十七条
DISEASE_WORDS = [
    "近视", "鼻炎", "胃炎", "胃病", "关节炎", "皮炎", "湿疹", "痤疮",
    "高血压", "高血脂", "高血糖", "糖尿病", "心脑血管", "冠心病", "血栓",
    "失眠", "便秘", "痔疮", "肝病", "肾虚", "前列腺", "妇科", "更年期",
    "癌", "肿瘤", "结石", "风湿", "颈椎", "腰椎", "骨质增生",
    "过敏", "咳嗽", "哮喘", "感冒", "发炎", "溃疡", "抑郁",
]

# 游戏赛道的违规形态与保健/化妆品完全不同：不是功效宣称，
# 而是「抽奖概率不公示」「奖励承诺与实际不符」「爆率宣传」。
# 法条依据是《广告法》第八条（允诺应当准确、清楚、明白），不是第十七/十八条。
GAME_TERMS = [
    "爆率", "超高爆率", "高爆率", "概率", "保底", "连抽", "抽卡", "抽奖",
    "必得", "必出", "稳出", "白嫖", "上线送", "免费送", "登录送", "充值送",
    "神装", "顶级装备", "无限", "秒杀", "变态版", "无氪", "零元",
    "专属", "限时", "随机抽取",
]

# 明显是产品名而非违规词面的信号：出现这些字样且不含功效动词的，多半是商品名
PRODUCT_MARKERS = ["牌", "胶囊", "片剂", "咀嚼片", "口服液", "颗粒", "丸", "面膜",
                   "精华", "乳液", "霜", "套装", "礼盒", "系列", "型号"]

# 新发现环节的停用词：这些跨案例高频但毫无判别力
STOPWORDS = {
    "我们", "广告", "发布", "安全", "作用", "有效", "进行", "可以", "产品",
    "公司", "使用", "销售", "宣传", "内容", "相关", "其他", "以及", "通过",
    "对于", "存在", "没有", "这个", "一个", "用户", "消费", "消费者", "服务",
    "游戏", "平台", "商品", "经营", "活动", "功能", "效果", "问题", "情况",
    "方式", "获得", "获取", "提供", "以上", "以下", "能够", "具有", "达到",
}

_SPLIT = re.compile(r"[、，,；;。.\n\r／/｜|（）()【】\[\]“”\"']+")
_CJK = re.compile(r"[一-鿿]")


# ══════════════════════════════════════════════════════════════════════
#  复核决策
# ══════════════════════════════════════════════════════════════════════
#
# 案例频次高 ≠ 可以进词库。把决策写在代码里而不是靠人记，是因为
# 每一条的理由都需要能被追问、被推翻、被重跑。
#
#   accept  法律上无争议的禁用表述，进词库
#   defer   有合法用法，误报代价高，留草稿等法务定夺
#   reject  不是词面问题，词库根本解决不了
#
# ⚠️ 最需要注意的是 defer 里的保健功能用语：
#    「增强免疫力」「改善睡眠」「缓解体力疲劳」都在国家批准的保健功能目录里，
#    是合规产品**可以依法宣称**的。把「增强」「改善」「缓解」收进禁用语，
#    会把所有合规保健食品广告全部打成违规 —— 这种误报比漏报更快毁掉信任。
# ══════════════════════════════════════════════════════════════════════

ACCEPT, DEFER, REJECT = "accept", "defer", "reject"

CURATION: dict[str, tuple[str, str]] = {
    # ── 疾病治疗类：法律上无争议 ──────────────────────────────
    "治疗": (ACCEPT, "非医疗类广告不得涉及疾病治疗功能，无抗辩空间"),
    "治愈": (ACCEPT, "同上，且属功效断言"),
    "根治": (ACCEPT, "同上，程度更重"),
    "痊愈": (ACCEPT, "同上"),
    "医治": (ACCEPT, "医疗用语"),
    "疗效": (ACCEPT, "功效断言 + 医疗用语"),
    "防治": (ACCEPT, "含治疗语义，保健食品明确禁止"),
    "抗癌": (ACCEPT, "疾病治疗功效，重灾区"),

    # ── 疾病名：在非医疗类广告里出现即高度可疑 ────────────────
    "癌": (ACCEPT, "提及具体疾病，构成疾病功效暗示"),
    "肿瘤": (ACCEPT, "同上"),
    "糖尿病": (ACCEPT, "同上"),
    "高血压": (ACCEPT, "同上"),
    "高血脂": (ACCEPT, "同上"),
    "心脑血管": (ACCEPT, "同上"),
    "冠心病": (ACCEPT, "同上"),
    "血栓": (ACCEPT, "同上"),
    "鼻炎": (ACCEPT, "同上"),
    "胃炎": (ACCEPT, "同上"),
    "关节炎": (ACCEPT, "同上"),
    "结石": (ACCEPT, "同上"),
    "哮喘": (ACCEPT, "同上"),
    "溃疡": (ACCEPT, "同上"),
    "近视": (ACCEPT, "同上；儿童护眼类重灾区"),

    # ── 法定保健功能用语：有合法用法，绝不能一刀切 ────────────
    "增强": (DEFER, "「增强免疫力」是法定保健功能，合规产品可依法宣称"),
    "改善": (DEFER, "「改善睡眠」「改善生长发育」均为法定保健功能"),
    "缓解": (DEFER, "「缓解体力疲劳」「缓解视疲劳」均为法定保健功能"),
    "调理": (DEFER, "语义宽泛，需结合是否指向疾病判断"),
    "滋补": (DEFER, "传统表述，本身不必然违规"),
    "修复": (DEFER, "化妆品「修护」类宣称常见且合法"),
    "预防": (DEFER, "保健食品不得涉及疾病预防；但「预防干燥」等非疾病语境合法，需看宾语"),
    "消除": (DEFER, "宾语决定性质：「消除疲劳」与「消除炎症」法律后果不同"),
    "清除": (DEFER, "同上"),
    "排毒": (DEFER, "非医学术语，是否构成疾病暗示有争议"),
    "抑制": (DEFER, "需看抑制对象"),
    "再生": (DEFER, "化妆品语境有合法用法"),

    # ── 化妆品：特殊化妆品的合法功效，属「需资质」不属「禁用」──
    "美白": (DEFER, "祛斑美白属特殊化妆品，注册后可合法宣称 —— 应归 L3 需资质而非 L2 禁用"),
    "祛斑": (DEFER, "同上"),
    "淡斑": (DEFER, "同上"),
    "生发": (DEFER, "育发类特殊化妆品，注册后合法"),
    "脱发": (DEFER, "同上"),
    "祛痘": (DEFER, "普通化妆品宣称祛痘的边界需法务确认"),
    "祛皱": (DEFER, "抗皱类宣称边界同上"),
    "去皱": (DEFER, "同上"),
    "减肥": (DEFER, "「减肥」是法定保健功能之一"),
    "瘦身": (DEFER, "同上"),
    "丰胸": (DEFER, "需确认是否属明确禁止的宣称"),
    "降血压": (DEFER, "「辅助降血压」是法定保健功能，去掉「辅助」才违规 —— 需看完整表述"),
    "降血脂": (DEFER, "同上"),
    "降血糖": (DEFER, "同上"),
    "过敏": (DEFER, "「敏感肌适用」等描述合法，需看语境"),
    "咳嗽": (DEFER, "需看是否构成疗效宣称"),
    "感冒": (DEFER, "同上"),
    "发炎": (DEFER, "同上"),
    "失眠": (DEFER, "「改善睡眠」合法，「治疗失眠」违法，取决于搭配"),
    "便秘": (DEFER, "「润肠通便」是法定保健功能"),
    "肾虚": (DEFER, "中医术语，监管口径需确认"),
    "更年期": (DEFER, "描述人群非疾病，需看语境"),

    # ── 游戏：多数不是词面问题 ────────────────────────────────
    "超高爆率": (ACCEPT, "夸张允诺，与实际掉落机制不符即构成虚假宣传"),
    "高爆率": (ACCEPT, "同上"),
    "爆率": (DEFER, "中性术语，需结合是否公示实际概率判断"),
    "概率": (REJECT, "概率本身合法，违规在于**未公示**——这是事实核验问题，词库解决不了"),
    "抽奖": (REJECT, "同上"),
    "抽卡": (REJECT, "同上"),
    "连抽": (REJECT, "描述玩法，不违规"),
    "保底": (REJECT, "描述机制，不违规"),
    "随机抽取": (REJECT, "描述事实，本身不违规"),
    "上线送": (REJECT, "允诺是否准确要看实际发放，属事实核验"),
    "专属": (REJECT, "通用营销词，无判别力"),
    "限时": (REJECT, "同上"),
}


@dataclass
class CaseRef:
    case_id: str
    industry: str
    penalty_amount: int | None
    source_url: str
    review_status: str


@dataclass
class Candidate:
    term: str
    kind: str                       # efficacy | disease | discovered
    cases: list[CaseRef] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)

    @property
    def case_count(self) -> int:
        return len({c.case_id for c in self.cases})

    @property
    def max_penalty(self) -> int:
        return max((c.penalty_amount or 0 for c in self.cases), default=0)

    @property
    def approved_count(self) -> int:
        return len({c.case_id for c in self.cases if c.review_status == "approved"})


def sector_of(industry: str) -> str | None:
    for sector, pats in SECTOR_PATTERNS.items():
        if any(p in (industry or "") for p in pats):
            return sector
    return None


def load_cases() -> list[dict]:
    cases = []
    for sub in ("structured", "structured_candidates"):
        d = DATA / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
                c["_dir"] = sub
                cases.append(c)
            except Exception as exc:  # 坏文件跳过但要说出来
                print(f"  [跳过] {p.name}: {exc}", file=sys.stderr)
    return cases


def looks_like_product_name(frag: str) -> bool:
    """疑似商品名：带商品标记词，且不含任何功效动词。"""
    if not any(m in frag for m in PRODUCT_MARKERS):
        return False
    return not any(v in frag for v in EFFICACY_VERBS)


def mine() -> dict[str, dict[str, Candidate]]:
    cases = load_cases()
    print(f"载入案例 {len(cases)} 条")

    # sector -> term -> Candidate
    result: dict[str, dict[str, Candidate]] = collections.defaultdict(dict)
    ngram_pool: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    ngram_cases: dict[str, dict[str, set]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )

    for c in cases:
        sector = sector_of(c.get("industry", ""))
        if sector is None:
            continue
        ref = CaseRef(
            case_id=c.get("case_id", "?"),
            industry=c.get("industry", ""),
            penalty_amount=c.get("penalty_amount"),
            source_url=c.get("source_url", ""),
            review_status=c.get("review_status", ""),
        )

        blob = " ".join(
            filter(None, [
                " ".join(c.get("illegal_claims") or []),
                c.get("facts_summary", ""),
                " ".join(c.get("keywords") or []),
            ])
        )

        # ── 种子词命中 ──
        # 游戏赛道用自己的种子表：它的违规形态是允诺不实与概率不公示，
        # 拿功效动词去扫游戏广告一个也扫不出来。
        seed_sets = (
            (("game", GAME_TERMS),)
            if sector == "game"
            else (("efficacy", EFFICACY_VERBS), ("disease", DISEASE_WORDS))
        )
        for kind, seeds in seed_sets:
            for w in seeds:
                if w in blob:
                    cand = result[sector].setdefault(w, Candidate(w, kind))
                    cand.cases.append(ref)

        # ── 未知说法发现：对违规宣称做 2-5 gram 频次统计 ──
        for claim in (c.get("illegal_claims") or []):
            for frag in _SPLIT.split(claim):
                frag = frag.strip()
                if len(frag) < 2 or not _CJK.search(frag):
                    continue
                if looks_like_product_name(frag):
                    continue
                for n in range(2, 7):
                    for i in range(len(frag) - n + 1):
                        g = frag[i:i + n]
                        if _CJK.search(g):
                            ngram_pool[sector][g] += 1
                            ngram_cases[sector][g].add(ref.case_id)
                # 保留完整片段作为类案证据
                for w in EFFICACY_VERBS + DISEASE_WORDS + GAME_TERMS:
                    if w in frag and w in result[sector]:
                        result[sector][w].claims.append(frag)

    all_seeds = set(EFFICACY_VERBS) | set(DISEASE_WORDS) | set(GAME_TERMS)

    for sector, counter in ngram_pool.items():
        known = set(result[sector])
        survivors: dict[str, int] = {}

        for g, _n in counter.most_common(1200):
            if g in known or g in STOPWORDS:
                continue
            if len(ngram_cases[sector][g]) < 3:      # 至少 3 个案例出现才算模式
                continue
            # 与种子表的关系要**双向**排除：
            #   「抗癌症」含种子「抗癌」→ 是变体，不重复列
            #   「心脑」被种子「心脑血管」包含 → 是碎片，更不该单列
            # 早期只查了前一个方向，结果 心脑/脑血/血管/免疫/疫力 全冒出来了。
            if any(s in g or g in s for s in all_seeds):
                continue
            survivors[g] = len(ngram_cases[sector][g])

        # 抑制碎片：若存在更长的候选把它整个包住、且覆盖的案例数几乎一样，
        # 说明它只是那个长词的一段，没有独立信息量。
        maximal = {
            g: c for g, c in survivors.items()
            if not any(g != h and g in h and survivors[h] >= c * 0.8 for h in survivors)
        }

        for g, _ in sorted(maximal.items(), key=lambda kv: -kv[1]):
            cand = Candidate(g, "discovered")
            cand.cases = [CaseRef(cid, "", None, "", "") for cid in ngram_cases[sector][g]]
            result[sector][g] = cand

    return result


SECTOR_CN = {"health_food": "保健食品", "cosmetics": "化妆品 / 医美", "game": "游戏"}
KIND_CN = {"efficacy": "功效宣称", "disease": "疾病症状",
           "game": "允诺/概率", "discovered": "★ 新发现"}


def write_review(result) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "L2_candidates_review.md"
    L = ["# L2 行业禁用语 · 候选词人工复核工作表", "",
         "> 本表由 `backend/scripts/mine_l2_terms.py` 从行政处罚案例库自动挖掘。",
         "> **这不是词库**：需人工逐条判断「是否作为违禁词面收录」，勾选后才能进 L2 词库。", "",
         "复核要点：", "",
         "- 该词是否**指向违规宣称本身**，而非产品名、行业通用词",
         "- 收进词库后会不会大面积误报（如「改善」在化妆品语境下极常见）",
         "- 标记 ★ 的是种子表之外、跨 3 个以上案例出现的说法——**这些是最值得看的**", ""]

    for sector, cands in result.items():
        rows = sorted(cands.values(), key=lambda c: (-c.case_count, -c.max_penalty, c.term))
        L += [f"## {SECTOR_CN.get(sector, sector)}（{len(rows)} 个候选）", "",
              "| 决策 | 候选词 | 类型 | 案例数 | 最高罚款 | 理由 / 案例中的实际表述 |",
              "|:--:|---|---|--:|--:|---|"]
        for c in rows:
            decision, reason = CURATION.get(c.term, ("", ""))
            mark = {ACCEPT: "✅ 已收录", DEFER: "⏸ 待定", REJECT: "❌ 不收"}.get(decision, "☐ 待判")
            note = reason or ("；".join(dict.fromkeys(c.claims))[:70] or "—")
            money = f"{c.max_penalty/10000:.1f}万" if c.max_penalty else "—"
            L.append(f"| {mark} | **{c.term}** | {KIND_CN[c.kind]} | {c.case_count} | "
                     f"{money} | {note} |")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


LEXICON_DIR = ROOT / "backend" / "app" / "rules" / "lexicon"

# 法条按赛道取，不能共用一条
_LAW_HEALTH = ("《广告法》第十七条 / 第十八条", "ad_law_17_18", "ADLAW-018")
_LAW_GENERAL = ("《广告法》第十七条", "ad_law_17", "ADLAW-017")
_LAW_GAME = ("《广告法》第八条 / 第二十八条", "ad_law_08_28", "ADLAW-028")


def write_lexicon(result) -> tuple[Path, dict]:
    """把复核通过的词条写成正式 L2 词库。

    同一个词可能在多个赛道都命中（「治疗」在保健食品和化妆品都有案例），
    **必须合并成一条**并列出全部适用行业 —— 词库里出现重复词面会让
    AC 自动机重复报同一个命中，报告里就会出现两条一模一样的风险。
    """
    # ⚠️ 词库是「法条基线 + 案例增强」，不是纯案例驱动。
    #
    # 踩过的坑：最初只收录案例库里出现过的词，结果「根治」「痊愈」「哮喘」
    # 这些法律上毫无争议的禁用语全部缺失 —— 只因为这 133 个案例里恰好
    # 没有它们。案例库是有限样本，拿它当词库的唯一来源必然留下覆盖盲区，
    # 而盲区意味着漏检，漏检的代价是客户被罚。
    #
    # 所以：CURATION 里标 accept 的一律进库；有案例的附上案号作为增强，
    # 没案例的照样收，只是 cases 为空。
    merged: dict[str, dict] = {
        term: {"sectors": set(), "cases": set(), "reason": reason}
        for term, (decision, reason) in CURATION.items()
        if decision == ACCEPT
    }
    for sector, cands in result.items():
        for term, cand in cands.items():
            if term not in merged:
                continue
            merged[term]["sectors"].add(sector)
            merged[term]["cases"].update(c.case_id for c in cand.cases)

    # 没有任何案例命中的词，按其语义归入默认赛道
    _DEFAULT_SECTOR = {"超高爆率": "game", "高爆率": "game"}
    for term, slot in merged.items():
        if not slot["sectors"]:
            slot["sectors"].add(_DEFAULT_SECTOR.get(term, "health_food"))

    L = ["# ══════════════════════════════════════════════════════════════",
         "#  L2 · 行业禁用语",
         "# ══════════════════════════════════════════════════════════════",
         "#",
         "# 由 backend/scripts/mine_l2_terms.py 从行政处罚案例库挖掘并按",
         "# 脚本内的 CURATION 决策表筛选后生成。**不要手改本文件**，",
         "# 要增删词条请改 CURATION 后重跑，否则下次生成会覆盖。",
         "#",
         "# 每条的 cases 是真实案号，报告里可据此写「该表述在 XX 案中被认定为…」，",
         "# 这是本词库相对凭经验列词的根本优势。",
         "#",
         "# ⚠️ 尚未经法务复核。另有一批高频但**有合法用法**的词被刻意排除",
         "#    （「增强免疫力」「改善睡眠」「缓解体力疲劳」都是法定保健功能，",
         "#    收进禁用语会把合规产品全打成违规），见 docs/L2_candidates_review.md。",
         "",
         "meta:",
         "  layer: L2",
         "  kind: terms",
         "  name: 行业禁用语",
         '  version: "0.1.0-auto"',
         "  reviewed_by_legal: false",
         "  generated_by: backend/scripts/mine_l2_terms.py",
         "",
         "law_texts:",
         "  ad_law_17: >-",
         "    《中华人民共和国广告法》第十七条：除医疗、药品、医疗器械广告外，",
         "    其他广告不得涉及疾病治疗功能，也不得使用医疗用语或者易使商品与药品、",
         "    医疗器械相混淆的用语。",
         "  ad_law_17_18: >-",
         "    《中华人民共和国广告法》第十七条：除医疗、药品、医疗器械广告外，",
         "    其他广告不得涉及疾病治疗功能……第十八条：保健食品广告不得含有下列内容：",
         "    （一）表示功效、安全性的断言或者保证；（二）涉及疾病预防、治疗功能……",
         "  ad_law_08_28: >-",
         "    《中华人民共和国广告法》第八条：广告中对商品的……允诺等有表示的，",
         "    应当准确、清楚、明白。第二十八条：广告以虚假或者引人误解的内容",
         "    欺骗、误导消费者的，构成虚假广告。",
         "",
         "entries:"]

    for term in sorted(merged, key=lambda t: (-len(merged[t]["cases"]), t)):
        slot = merged[term]
        sectors = sorted(slot["sectors"])
        cases = sorted(slot["cases"])
        if "game" in sectors:
            law, ref, rule_id = _LAW_GAME
        elif "health_food" in sectors:
            law, ref, rule_id = _LAW_HEALTH
        else:
            law, ref, rule_id = _LAW_GENERAL

        L += [f"  - term: {term}",
              f"    industry: [{', '.join(sectors)}]",
              f'    law_ref: "{law}"',
              f"    law_text_ref: {ref}",
              f'    rule_id: "{rule_id}"',
              f'    judgment_points: "{slot["reason"]}"',
              f"    risk: {'high' if len(cases) >= 4 else 'medium'}",
              f"    cases: [{', '.join(cases[:8])}]"
              + ("" if cases else "   # 法条基线词，本案例库暂无对应处罚案例"),
              ""]

    LEXICON_DIR.mkdir(parents=True, exist_ok=True)
    path = LEXICON_DIR / "L2_industry.yaml"
    path.write_text("\n".join(L), encoding="utf-8")
    return path, merged


def write_draft(result) -> Path:
    """草稿词库。只收「种子命中且跨 2 个以上案例」的，发现项一律不自动收录。"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "L2_draft.yaml"

    L = ["# L2 · 行业禁用语（草稿，自动生成）",
         "#",
         "# ⚠️ 本文件由 mine_l2_terms.py 生成，**未经法务复核，不得用于对外报告**。",
         "# ⚠️ 只收录了「种子词命中且跨 2 个以上案例」的条目；",
         "#    自动发现的新说法一律未收录，见 L2_candidates_review.md 由人工决定。",
         "#",
         "# 每条的 cases 字段是真实案号——报告里可据此写",
         "# 「该表述在 XX 案中被认定为……」，这是本词库相对凭经验列词的根本优势。",
         "",
         "meta:",
         "  layer: L2",
         "  kind: terms",
         "  name: 行业禁用语",
         '  version: "0.1.0-auto"',
         "  reviewed_by_legal: false",
         "  generated_from: data (structured + structured_candidates)",
         "",
         "law_texts:",
         "  ad_law_17: >-",
         "    《中华人民共和国广告法》第十七条：除医疗、药品、医疗器械广告外，",
         "    其他广告不得涉及疾病治疗功能，也不得使用医疗用语或者易使商品与药品、",
         "    医疗器械相混淆的用语。",
         "  ad_law_18: >-",
         "    《中华人民共和国广告法》第十八条：保健食品广告不得含有下列内容：",
         "    （一）表示功效、安全性的断言或者保证；（二）涉及疾病预防、治疗功能……",
         "  ad_law_08: >-",
         "    《中华人民共和国广告法》第八条：广告中对商品的性能、功能、产地、用途、",
         "    质量、规格、成分、价格、生产者、有效期限、允诺等或者对服务的内容、",
         "    提供者、形式、质量、价格、允诺等有表示的，应当准确、清楚、明白。",
         "",
         "entries:"]

    # 三个赛道的法条依据完全不同，不能共用一条。
    # ⚠️ 游戏这一路对应《广告法》第八条（允诺应当准确清楚明白），
    #    但 refs/data/rules/advertising_law_2021.json 的规则目录里**没有第八条**，
    #    所以 rule_id 暂时挂到 ADLAW-028（虚假广告）上，并在此标记待补。
    SECTOR_LAW = {
        "health_food": ("《广告法》第十八条", "ad_law_18", "ADLAW-018", ""),
        "cosmetics": ("《广告法》第十七条", "ad_law_17", "ADLAW-017", ""),
        "game": ("《广告法》第八条", "ad_law_08", "ADLAW-028",
                 "  # ⚠️ 待补：规则目录缺 ADLAW-008，第八条才是允诺不实的直接依据"),
    }

    for sector, cands in result.items():
        rows = [c for c in cands.values() if c.kind != "discovered" and c.case_count >= 2]
        if not rows:
            continue
        law, ref, rule_id, warn = SECTOR_LAW.get(
            sector, ("《广告法》第二十八条", "ad_law_17", "ADLAW-028", "")
        )
        L.append(f"  # ── {SECTOR_CN.get(sector, sector)} ──")
        for c in sorted(rows, key=lambda x: -x.case_count):
            L += [f"  - term: {c.term}",
                  f"    industry: [{sector}]",
                  f'    law_ref: "{law}"',
                  f"    law_text_ref: {ref}",
                  f'    rule_id: "{rule_id}"{warn}',
                  f"    risk: {'high' if c.case_count >= 4 else 'medium'}",
                  f"    cases: [{', '.join(sorted({x.case_id for x in c.cases})[:6])}]",
                  ""]
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def main() -> None:
    if not DATA.is_dir():
        sys.exit(f"找不到案例库目录：{DATA}")

    result = mine()

    print()
    for sector, cands in result.items():
        seeds = [c for c in cands.values() if c.kind != "discovered"]
        found = [c for c in cands.values() if c.kind == "discovered"]
        print(f"{SECTOR_CN.get(sector, sector):<12} 种子命中 {len(seeds):>3} 个 · "
              f"新发现 {len(found):>3} 个")

    lex, merged = write_lexicon(result)
    r = write_review(result)
    d = write_draft(result)

    seen = {t for cands in result.values() for t in cands}
    tally = collections.Counter(
        CURATION.get(t, ("待判", ""))[0] for t in seen
    )
    print(f"\n复核决策：已收录 {tally.get(ACCEPT, 0)} · "
          f"待定 {tally.get(DEFER, 0)} · 不收 {tally.get(REJECT, 0)} · "
          f"未判 {tally.get('待判', 0)}")

    print(f"\n正式词库   → {lex.relative_to(ROOT)}　（{len(merged)} 条）")
    print(f"复核工作表 → {r.relative_to(ROOT)}")
    print(f"草稿全量   → {d.relative_to(ROOT)}")
    print("\n⚠️ 正式词库仍未经法务复核，标记为 reviewed_by_legal: false。")
    print("   「增强/改善/缓解」等法定保健功能用语已刻意排除，理由见工作表。")


if __name__ == "__main__":
    main()
