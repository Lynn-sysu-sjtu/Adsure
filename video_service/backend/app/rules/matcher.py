"""违禁词粗筛：AC 自动机 + 白名单抑制。

本模块的职责边界必须说清楚：**它只负责高召回地"找到嫌疑"，不负责定性。**

原因是广告法违规高度语境依赖，纯词匹配的误报率高到不可用：
    最新款 ✅  /  最好用 ❌        —— "最"后面接什么
    第一时间发货 ✅ / 第一品牌 ❌   —— 时间副词 vs 排名断言
    特级初榨橄榄油 ✅ / 特级棒 ❌   —— 是否国标术语
    销量第一（附第三方可查证来源）✅ / 销量第一（无出处）❌ —— 有无举证

所以链路是「AC 粗筛（宽） → LLM 语境复判（严）」两级。
本模块产出的 Hit 会带上上下文、法条原文、判定要点、豁免线索一起交给 LLM，
**不让 LLM 自己编法条** —— 这是审心的核心卖点，视频这一路原样继承。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import get_settings
from app.rules.schema import KIND_TERMS, KIND_REQUIREMENTS
from app.pipeline.evidence import (
    BBox,
    EvidenceBundle,
    EvidenceSource,
    TextEvidence,
    TranscriptIndex,
)

logger = logging.getLogger(__name__)

LEXICON_DIR = Path(__file__).parent / "lexicon"


# ──────────────────────────────────────────────────────────────
#  词库
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LexiconEntry:
    term: str
    level: str
    industry: tuple[str, ...]
    law_ref: str
    law_text: str
    risk: str
    judgment_points: str = ""
    whitelist_contexts: tuple[str, ...] = ()
    exempt_hints: tuple[str, ...] = ()

    cases: tuple[str, ...] = ()
    """挖词时记录的处罚案例出处。涵摄时据此**直接**取类案，
    比相似度检索准得多 —— 这就是「该表述在这些案子里被罚过」。"""

    rule_id: str = ""
    """对齐团队既有规则目录（ADLAW-xxx），涵摄层据此找构成要件。"""

    required_materials: tuple[str, ...] = ()
    """L3 需资质/需授权词命中后要求运营补充的材料清单。
    与 IP 命中同走「要材料」处置路径：文案写「专利」要专利证书，
    画面出现米奇要迪士尼授权书 —— 同一个处置模式。L1/L2 词条为空。"""

    def applies_to(self, industry: str | None) -> bool:
        if "*" in self.industry:
            return True
        return industry is not None and industry in self.industry


@dataclass
class Lexicon:
    entries: list[LexiconEntry] = field(default_factory=list)
    global_whitelist: list[str] = field(default_factory=list)
    reviewed_by_legal: bool = False

    @classmethod
    def load_file(cls, path: Path) -> Lexicon:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        meta = raw.get("meta", {})
        level = meta.get("layer", "L?")
        law_texts: dict[str, str] = raw.get("law_texts", {})
        common_hints: list[str] = raw.get("common_exempt_hints", [])

        entries: list[LexiconEntry] = []
        for item in raw.get("entries", []):
            law_text = item.get("law_text") or law_texts.get(item.get("law_text_ref", ""), "")
            if not law_text:
                # 宁可报错也不能让 LLM 拿着空法条去推理 —— 那就退化成"AI 自己编法条"了
                raise ValueError(
                    f"{path.name} 中词条「{item.get('term')}」缺少 law_text/law_text_ref，"
                    "法条原文是喂给 LLM 的硬前提，不允许为空。"
                )
            entries.append(
                LexiconEntry(
                    term=item["term"],
                    level=item.get("level", level),
                    industry=tuple(item.get("industry", ["*"])),
                    law_ref=item["law_ref"],
                    law_text=law_text.strip(),
                    risk=item.get("risk", "medium"),
                    judgment_points=item.get("judgment_points", ""),
                    whitelist_contexts=tuple(item.get("whitelist_contexts", [])),
                    exempt_hints=tuple(item.get("exempt_hints", [])) + tuple(common_hints),
                    cases=tuple(item.get("cases", [])),
                    rule_id=item.get("rule_id", ""),
                    required_materials=tuple(item.get("required_materials", [])),
                )
            )

        return cls(
            entries=entries,
            global_whitelist=list(raw.get("global_whitelist", [])),
            reviewed_by_legal=bool(meta.get("reviewed_by_legal", False)),
        )

    @classmethod
    def load_dir(cls, directory: Path | None = None) -> Lexicon:
        """加载目录下所有**词面型**词库，跳过其他 schema。"""
        directory = directory or LEXICON_DIR
        files = sorted(directory.glob("*.yaml"))
        if not files:
            raise FileNotFoundError(f"词库目录为空: {directory}")

        merged = cls()
        loaded, unreviewed = [], []
        for path in files:
            meta = yaml.safe_load(path.read_text(encoding="utf-8")).get("meta") or {}
            kind = meta.get("kind")
            if kind is None:
                raise ValueError(
                    f"{path.name} 的 meta 缺少 kind 字段。"
                    f"请声明 kind: {KIND_TERMS}（词面型）或 kind: {KIND_REQUIREMENTS}（必备要素型）。"
                )
            if kind != KIND_TERMS:
                continue

            part = cls.load_file(path)
            merged.entries.extend(part.entries)
            merged.global_whitelist.extend(part.global_whitelist)
            loaded.append(path.name)
            if not part.reviewed_by_legal:
                unreviewed.append(path.name)

        if not loaded:
            raise FileNotFoundError(f"{directory} 下没有任何词面型（kind: {KIND_TERMS}）词库")

        # 必须是「全部都过了法务复核」才算复核过。
        # 早期这里写的是 or —— 只要有一份过了就把整个词库标成已复核，
        # 那会让未复核的词条搭便车进入对外报告。
        merged.reviewed_by_legal = not unreviewed
        if unreviewed:
            logger.warning(
                "以下词库尚未经法务复核，输出仅供内部验证，不得用于对外报告: %s",
                ", ".join(unreviewed),
            )
        return merged


# ──────────────────────────────────────────────────────────────
#  命中
# ──────────────────────────────────────────────────────────────


@dataclass
class Hit:
    """一次违禁词命中。带齐 LLM 复判所需的全部上下文。"""

    entry: LexiconEntry
    matched_text: str

    evidence_id: str
    source: EvidenceSource
    char_start: int
    char_end: int

    t_start: float
    t_end: float

    context: str
    """命中词前后各若干字的原文。LLM 判"最新款"还是"最好用"全靠它。"""

    bbox: BBox | None = None
    font_scale: float | None = None

    def to_llm_payload(self) -> dict:
        """喂给涵摄推理的结构。严格只给事实与规则，不给结论。"""
        return {
            "命中词": self.matched_text,
            "上下文原文": self.context,
            "出现时间": f"{self.t_start:.2f}s - {self.t_end:.2f}s",
            "来源": "口播" if self.source == EvidenceSource.ASR else "画面文字",
            "法律依据": self.entry.law_ref,
            "法条原文": self.entry.law_text,
            "判定要点": self.entry.judgment_points,
            "豁免情形核查": list(self.entry.exempt_hints),
            "参考类案": list(self.entry.cases),
            "需核验材料": list(self.entry.required_materials),
        }


# ──────────────────────────────────────────────────────────────
#  AC 自动机封装
# ──────────────────────────────────────────────────────────────


def _build_automaton(patterns: list[str]):
    """构造 leftmost-longest 语义的 AC 自动机。

    用 leftmost-longest 而非 standard：命中"最高级"时不应该同时报"最高"，
    词库场景下总是取最长匹配才对。
    """
    try:
        from ahocorasick_rs import AhoCorasick, MatchKind
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "未安装 ahocorasick-rs，请先 pip install -r requirements.txt"
        ) from exc

    try:
        return AhoCorasick(patterns, matchkind=MatchKind.LeftmostLongest)
    except (AttributeError, TypeError):  # 兼容旧版本的模块级常量写法
        import ahocorasick_rs

        return AhoCorasick(patterns, matchkind=ahocorasick_rs.MATCHKIND_LEFTMOST_LONGEST)


class _Automaton:
    """带索引口径自检的 AC 自动机。

    ⚠️ 这个自检是刻意加的，不是防御性冗余。
    ahocorasick_rs 返回的 (start, end) 在不同版本 / 不同调用方式下可能是
    **字符索引**也可能是**字节索引**。中文下 UTF-8 一个汉字占 3 字节，
    口径搞错会让所有时间戳静默偏移 —— 而时间戳准确性是这个产品的命根子，
    错了不会报错，只会让报告悄悄指向错误的秒数。
    所以初始化时用中文探针判定一次，之后按判定结果换算。
    """

    _PROBE = "甲乙丙丁"

    def __init__(self, patterns: list[str]):
        self.patterns = patterns
        self._ac = _build_automaton(patterns) if patterns else None
        self._byte_indexed = self._detect_byte_indexed()

    def _detect_byte_indexed(self) -> bool:
        if self._ac is None:
            return False
        probe_pattern = self._PROBE[2]  # "丙"，前面有 2 个汉字
        probe_ac = _build_automaton([probe_pattern])
        matches = probe_ac.find_matches_as_indexes(self._PROBE)
        if not matches:
            raise RuntimeError("AC 自动机自检失败：探针未命中，词匹配不可信，拒绝继续。")
        _, start, _ = matches[0]
        if start == 2:
            return False  # 字符索引
        if start == 6:
            return True  # 字节索引（2 个汉字 × 3 字节）
        raise RuntimeError(
            f"AC 自动机索引口径无法识别（探针返回 start={start}，期望 2 或 6）。"
            "词匹配的时间戳定位不可信，拒绝继续。"
        )

    def find(self, haystack: str) -> list[tuple[int, int, int]]:
        """返回 [(pattern_index, char_start, char_end), ...]，一律换算成**字符**索引。"""
        if self._ac is None:
            return []
        raw = self._ac.find_matches_as_indexes(haystack)
        if not self._byte_indexed:
            return list(raw)

        encoded = haystack.encode("utf-8")
        out: list[tuple[int, int, int]] = []
        for idx, b_start, b_end in raw:
            c_start = len(encoded[:b_start].decode("utf-8", errors="ignore"))
            c_end = len(encoded[:b_end].decode("utf-8", errors="ignore"))
            out.append((idx, c_start, c_end))
        return out


# ──────────────────────────────────────────────────────────────
#  匹配器
# ──────────────────────────────────────────────────────────────


class Matcher:
    def __init__(self, lexicon: Lexicon, context_window: int = 30):
        self.lexicon = lexicon
        self.context_window = context_window

        self._terms = [e.term for e in lexicon.entries]
        self._entry_by_index = list(lexicon.entries)
        self._term_automaton = _Automaton(self._terms)

        # 白名单 = 全局白名单 ∪ 各词条自带的白名单语境
        whitelist = list(lexicon.global_whitelist)
        for e in lexicon.entries:
            whitelist.extend(e.whitelist_contexts)
        self._whitelist = sorted(set(whitelist))
        self._whitelist_automaton = _Automaton(self._whitelist)

    # ── 内部 ──────────────────────────────────────────────────

    def _whitelist_spans(self, text: str) -> list[tuple[int, int]]:
        return [(s, e) for _, s, e in self._whitelist_automaton.find(text)]

    @staticmethod
    def _covered(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        """命中是否被某个白名单短语完整包住。

        必须是**完整包含**而非相交："第一时间"包住"第一" → 抑制；
        但如果只是部分重叠，说明是两个不同的表述，不该抑制。
        """
        return any(s <= start and end <= e for s, e in spans)

    def _context(self, text: str, start: int, end: int) -> str:
        lo = max(0, start - self.context_window)
        hi = min(len(text), end + self.context_window)
        prefix = "…" if lo > 0 else ""
        suffix = "…" if hi < len(text) else ""
        return f"{prefix}{text[lo:hi]}{suffix}"

    def _match_text(
        self,
        text: str,
        industry: str | None,
        resolve,
    ) -> list[Hit]:
        """在一段文本上跑匹配。

        resolve(char_start, char_end) -> (evidence, t_start, t_end) | None
        由调用方注入，因为 ASR（拼接文档）和 OCR（单条）的换算方式不同。
        """
        if not text.strip():
            return []

        whitelist_spans = self._whitelist_spans(text)
        hits: list[Hit] = []

        for pattern_idx, start, end in self._term_automaton.find(text):
            entry = self._entry_by_index[pattern_idx]
            if not entry.applies_to(industry):
                continue
            if self._covered(start, end, whitelist_spans):
                logger.debug("白名单抑制: %s @ %d-%d", entry.term, start, end)
                continue

            resolved = resolve(start, end)
            if resolved is None:
                logger.warning("命中 %s 无法定位到证据单元，跳过", entry.term)
                continue
            evidence, t_start, t_end = resolved

            hits.append(
                Hit(
                    entry=entry,
                    matched_text=text[start:end],
                    evidence_id=evidence.id,
                    source=evidence.source,
                    char_start=start,
                    char_end=end,
                    t_start=t_start,
                    t_end=t_end,
                    context=self._context(text, start, end),
                    bbox=evidence.bbox,
                    font_scale=evidence.font_scale,
                )
            )
        return hits

    @staticmethod
    def _speech_segments(
        units: list[TextEvidence], max_gap: float
    ) -> list[list[TextEvidence]]:
        """把口播证据按停顿切成若干段连续语流。

        段内可以跨句匹配（那是同一口气说下来的话），段间不行。
        """
        ordered = sorted(units, key=lambda e: e.t_start)
        segments: list[list[TextEvidence]] = []
        for unit in ordered:
            if segments and unit.t_start - segments[-1][-1].t_end <= max_gap:
                segments[-1].append(unit)
            else:
                segments.append([unit])
        return segments

    # ── 对外 ──────────────────────────────────────────────────

    def match_bundle(
        self,
        bundle: EvidenceBundle,
        industry: str | None = None,
        asr_join_max_gap: float | None = None,
    ) -> list[Hit]:
        """在一条视频的全部文本证据上跑匹配。

        ASR 与 OCR 的匹配语义**必须分开**：

        - ASR 是连续语流，违禁词可能横跨 provider 切出的两句
          （"……国家" + "级配方……"），必须拼成一篇整体匹配，否则漏检。
        - OCR 每块文字是画面上独立的一处，跨块拼接会造出现实中不存在的词
          （画面上方"最" + 下方"好用" ≠ "最好用"），必须逐条匹配。

        且 ASR 的拼接要**按连续语流分段**：相隔十几秒的两句话拼在一起，
        虽然不影响命中位置，却会让报告里的「上下文」出现现实中没有
        连着说过的句子——而上下文正是给法务做判断的证据，不能失真。
        """
        if asr_join_max_gap is None:
            asr_join_max_gap = get_settings().pipeline.asr_join_max_gap_seconds

        hits: list[Hit] = []

        # ── 口播：按连续语流分段，段内拼接整体匹配 ──
        for segment in self._speech_segments(
            bundle.texts(EvidenceSource.ASR), asr_join_max_gap
        ):
            index = TranscriptIndex(segment, join_all=True)
            hits.extend(
                self._match_text(index.document, industry, resolve=index.resolve)
            )

        # ── 画面文字：逐条匹配 ──
        for unit in bundle.texts(EvidenceSource.OCR):
            def _resolve(s: int, e: int, _u: TextEvidence = unit):
                t0, t1 = _u.resolve_time(s, e)
                return _u, t0, t1

            hits.extend(self._match_text(unit.text, industry, resolve=_resolve))

        hits.sort(key=lambda h: (h.t_start, h.char_start))
        logger.info("违禁词粗筛完成：%d 条命中（行业=%s）", len(hits), industry or "通用")
        return hits


def load_default_matcher(context_window: int = 30) -> Matcher:
    return Matcher(Lexicon.load_dir(), context_window=context_window)
