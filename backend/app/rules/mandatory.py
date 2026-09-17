"""L4：必备要素缺失检测 + 显著性核查。

本模块回答两个 AC 自动机回答不了的问题：

    ① 法律要求必须出现的提示语，**有没有出现**？
       —— 违禁词库查的是「不该出现的词」，这里查的是「该出现却没出现」。
          缺失没有词面可匹配，只能逐条要求去证据流里找。

    ② 出现了，但**够不够显著**？
       —— 「本品不能代替药物」写了，可是只闪了 0.4 秒、字高只占画面 1.8%、
          还藏在右下角。文本审核工具连它存在都无从知晓，更判不了显著性。
          这是本产品相对文本工具的核心差异化能力。

⚠️ 措辞边界：法律上「显著」无统一量化标准，监管认定需结合整体情境。
   本模块的阈值是**人工复核触发线**，输出一律表述为「建议复核 /
   存在被认定为未显著标明的风险」，绝不表述为「已构成违规」。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from app.pipeline.evidence import BBox, EvidenceBundle, EvidenceSource, TextEvidence
from app.rules.schema import KIND_REQUIREMENTS

logger = logging.getLogger(__name__)

LEXICON_PATH = Path(__file__).parent / "lexicon" / "L4_mandatory.yaml"
_WS = re.compile(r"[\s　]+")

# 短语太短时不做模糊匹配，否则「广告」会匹配上「广告法」之类
_FUZZY_MIN_LEN = 6

# standalone 模式下要剥掉的装饰字符：角标常写成「【广告】」「[广告]」
_DECOR = "【】[]()（）<>《》「」·|｜/\\-—:：、,，。.!！ \t"

# 标识与品牌名之间的分隔符，用来界定标识是否独立成词
_SEPARATORS = ("|", "｜", "·", "/", "-", "—", ":", "：", "、", ",", "，", " ")


def _norm(s: str) -> str:
    return _WS.sub("", s)


class MandatoryStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    NOT_SALIENT = "not_salient"
    SPOKEN_ONLY = "spoken_only"

    @property
    def label(self) -> str:
        return {
            "ok": "已显著标明",
            "missing": "未发现该必备提示语",
            "not_salient": "已出现但可能未显著标明",
            "spoken_only": "仅口播提及，画面未见标注",
        }[self.value]


@dataclass(frozen=True)
class SalienceRule:
    min_duration: float = 1.0
    min_font_scale: float = 0.025
    forbid_edge: bool = True
    edge_margin: float = 0.08


class MatchMode(StrEnum):
    CONTAINS = "contains"
    """必备表述出现在文本块中即可。适用于长句免责声明。"""

    STANDALONE = "standalone"
    """必备表述必须**自成一个独立标识**，不能是正文里的一个词。

    《广告法》第十四条要求「显著标明『广告』，与其他非广告信息相区别」——
    重点在「相区别」：正文里出现「广告」二字不构成标识。
    实测证据：一条广告合规产品的演示视频，画面里满是「广告合规」「广告法」，
    用 contains 模式会判定「已显著标明」并通过——这是**假通过**，
    比误报危险得多，等于替客户签字说这条片子没问题。
    """


@dataclass(frozen=True)
class MandatoryRequirement:
    id: str
    name: str
    industry: tuple[str, ...]
    required_any: tuple[str, ...]
    law_ref: str
    law_text: str
    remedy: str
    risk: str
    salience: SalienceRule
    match: MatchMode = MatchMode.CONTAINS
    forbidden_contexts: tuple[str, ...] = ()
    """命中若落在这些词组内则不算数，如「广告」落在「广告法」里。"""

    advisory: bool = False
    """仅提示，不计入风险数。

    用于那些**系统无法独立判断是否真的构成问题**的核查项 ——
    典型如广告可识别性标识：抖音、快手的「广告」角标由平台侧添加，
    不在创意素材里，对着素材查必然全报缺失。这种项若计入风险数，
    每条片子都会挂一条，真正的问题反而被淹没。

    ⚠️ 与「通过」是两回事：核查确实没通过，结论照常产出、照常进报告，
    只是不计入风险总数、不参与风险定级。降级的是权重，不是事实。"""

    note: str = ""

    def applies_to(self, industry: str | None) -> bool:
        if "*" in self.industry:
            return True
        return industry is not None and industry in self.industry


@dataclass
class Measure:
    """一项显著性度量。measured / threshold 均已格式化，可直接进报告。"""

    name: str
    measured: str
    threshold: str
    passed: bool

    def __str__(self) -> str:
        mark = "达标" if self.passed else "未达标"
        return f"{self.name} {self.measured}（阈值 {self.threshold}）{mark}"


@dataclass
class MandatoryFinding:
    requirement: MandatoryRequirement
    status: MandatoryStatus
    evidence: TextEvidence | None = None
    measures: list[Measure] = field(default_factory=list)

    @property
    def is_risk(self) -> bool:
        """核查未通过。**与是否计入风险数无关**，见 counts_as_risk。"""
        return self.status is not MandatoryStatus.OK

    @property
    def counts_as_risk(self) -> bool:
        """是否计入风险总数与风险定级。

        统计、定级、摘要一律用这个；`is_risk` 只表示「这项没过」。
        两者分开是刻意的：把仅提示项当成通过会掩盖事实，
        把它计入风险数又会淹没真正的问题，只能分成两个概念。
        """
        return self.is_risk and not self.requirement.advisory

    @property
    def failed_measures(self) -> list[Measure]:
        return [m for m in self.measures if not m.passed]

    def to_llm_payload(self) -> dict:
        """喂给涵摄推理的结构。只给事实与规则，不下结论。"""
        payload: dict = {
            "必备要素": self.requirement.name,
            "核查结果": self.status.label,
            "可接受的表述": list(self.requirement.required_any),
            "法律依据": self.requirement.law_ref,
            "法条原文": self.requirement.law_text,
            "整改方向": self.requirement.remedy,
            "措辞要求": (
                "法律上「显著」无统一量化标准，以下度量为人工复核触发线，"
                "不构成违法认定，结论须表述为「建议复核」而非「已构成违规」。"
            ),
        }
        if self.requirement.advisory:
            payload["处理层级"] = (
                "仅提示，不计入风险数。本项系统无法独立判断是否真的构成问题，"
                "结论须表述为「请确认」，不得升级为风险项或写入风险等级。"
            )
        if self.requirement.note:
            payload["特别说明"] = self.requirement.note
        if self.evidence is not None:
            payload["出现位置"] = f"{self.evidence.t_start:.2f}s - {self.evidence.t_end:.2f}s"
            payload["原文"] = self.evidence.text
            payload["来源"] = (
                "口播" if self.evidence.source == EvidenceSource.ASR else "画面文字"
            )
        if self.measures:
            payload["显著性度量"] = [
                {"项目": m.name, "实测": m.measured, "阈值": m.threshold, "达标": m.passed}
                for m in self.measures
            ]
        return payload


# ──────────────────────────────────────────────────────────────
#  加载
# ──────────────────────────────────────────────────────────────


def load_requirements(path: Path | None = None) -> list[MandatoryRequirement]:
    path = path or LEXICON_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    meta = raw.get("meta") or {}

    # 词库目录里混着两种 schema，加载错了会得到一堆莫名其妙的 KeyError。
    # 这里显式挡一道，报错要说清楚拿错了哪一份。
    kind = meta.get("kind")
    if kind != KIND_REQUIREMENTS:
        raise ValueError(
            f"{path.name} 的 kind 是 {kind!r}，本加载器只接受 {KIND_REQUIREMENTS!r}（必备要素型）。"
            f"词面型词库（L1/L2/L3）请用 matcher.Lexicon 加载。"
        )

    law_texts: dict[str, str] = raw.get("law_texts", {})
    defaults = (raw.get("defaults") or {}).get("salience") or {}

    if not meta.get("reviewed_by_legal", False):
        logger.warning("L4 词库尚未经法务复核，输出仅供内部验证，不得用于对外报告。")

    out: list[MandatoryRequirement] = []
    for item in raw.get("entries", []):
        law_text = item.get("law_text") or law_texts.get(item.get("law_text_ref", ""), "")
        if not law_text:
            raise ValueError(
                f"必备要素「{item.get('id')}」缺少 law_text/law_text_ref。"
                "法条原文是喂给 LLM 的硬前提，为空等于放任 AI 自己编法条。"
            )
        sal = {**defaults, **(item.get("salience") or {})}
        out.append(
            MandatoryRequirement(
                id=item["id"],
                name=item["name"],
                industry=tuple(item.get("industry", ["*"])),
                required_any=tuple(item["required_any"]),
                law_ref=item["law_ref"],
                law_text=law_text.strip(),
                remedy=item.get("remedy", ""),
                risk=item.get("risk", "medium"),
                salience=SalienceRule(**sal),
                match=MatchMode(item.get("match", MatchMode.CONTAINS)),
                forbidden_contexts=tuple(item.get("forbidden_contexts", [])),
                advisory=bool(item.get("advisory", False)),
                note=item.get("note", ""),
            )
        )
    return out


# ──────────────────────────────────────────────────────────────
#  核查
# ──────────────────────────────────────────────────────────────


def _edge_description(bbox: BBox) -> tuple[str, float]:
    """返回（位置描述, 距最近边缘的比例）。"""
    gaps = {
        "左": bbox.x,
        "上": bbox.y,
        "右": 1.0 - (bbox.x + bbox.w),
        "下": 1.0 - (bbox.y + bbox.h),
    }
    nearest = min(gaps, key=lambda k: gaps[k])
    return f"距{nearest}边缘 {gaps[nearest] * 100:.1f}%", gaps[nearest]


class MandatoryChecker:
    def __init__(
        self,
        requirements: list[MandatoryRequirement] | None = None,
        fuzzy_threshold: int = 80,
    ):
        self.requirements = requirements if requirements is not None else load_requirements()
        self.fuzzy_threshold = fuzzy_threshold

    # ── 匹配 ──────────────────────────────────────────────────

    def _text_hits(self, req: MandatoryRequirement, text: str) -> bool:
        """证据文本里是否出现了该必备表述。

        两种模式，用错方向都会出事：

        contains（长句免责声明）**必须容错模糊匹配** —— 这里的违规形态
            恰恰是「字太小」，而小字的 OCR 错误率本就高。只做精确匹配的话，
            被识别成「本品不能代誓药物」的提示语会判成「根本没写」，
            定性从「排版问题」错成「完全遗漏」，整改方向也跟着错。

        standalone（短标识）**必须严格**，且不做模糊匹配 —— 短标识一旦放宽，
            正文里随便出现两个字就判「已合规」，属于假通过。
        """
        n = _norm(text)
        if not n:
            return False

        for want in req.required_any:
            w = _norm(want)
            if not w:
                continue

            if req.match is MatchMode.STANDALONE:
                if self._standalone_hit(w, n):
                    return True
                continue

            if w in n and not self._in_forbidden_context(req, w, n):
                return True
            if len(w) >= _FUZZY_MIN_LEN and fuzz.partial_ratio(w, n) >= self.fuzzy_threshold:
                return True
        return False

    @staticmethod
    def _in_forbidden_context(req: MandatoryRequirement, want: str, text: str) -> bool:
        """命中是否被某个禁止语境整个吞掉（如「广告」落在「广告法」里）。"""
        return any(
            _norm(ctx) in text and want in _norm(ctx) for ctx in req.forbidden_contexts
        )

    @staticmethod
    def _standalone_hit(want: str, text: str) -> bool:
        """文本块是否**就是**这个标识，而不是把它包在正文里。

        接受：  「广告」「广告|某品牌」「某品牌·广告」「【广告】」
        拒绝：  「广告合规审核系统」「本广告仅供参考」「广告法」
        """
        stripped = text.strip(_DECOR)
        if stripped == want:
            return True
        # 角标常写成「广告 | 品牌」「品牌 · 推广」这种，用分隔符界定边界
        for sep in _SEPARATORS:
            if stripped.startswith(want + sep) or stripped.endswith(sep + want):
                return True
        return False

    # ── 显著性 ────────────────────────────────────────────────

    def measure_salience(self, req: MandatoryRequirement, ev: TextEvidence) -> list[Measure]:
        rule = req.salience
        out: list[Measure] = [
            Measure(
                "持续时长",
                f"{ev.duration:.2f} 秒",
                f"不少于 {rule.min_duration:.1f} 秒",
                ev.duration >= rule.min_duration,
            )
        ]
        if ev.font_scale is not None:
            out.append(
                Measure(
                    "字号占画面高度",
                    f"{ev.font_scale * 100:.1f}%",
                    f"不低于 {rule.min_font_scale * 100:.1f}%",
                    ev.font_scale >= rule.min_font_scale,
                )
            )
        if rule.forbid_edge and ev.bbox is not None:
            desc, _ = _edge_description(ev.bbox)
            out.append(
                Measure(
                    "画面位置",
                    desc,
                    f"距边缘不少于 {rule.edge_margin * 100:.0f}%",
                    not ev.bbox.near_edge(rule.edge_margin),
                )
            )
        return out

    # ── 主流程 ────────────────────────────────────────────────

    def check_bundle(
        self, bundle: EvidenceBundle, industry: str | None = None
    ) -> list[MandatoryFinding]:
        texts = bundle.texts()
        ocr = [e for e in texts if e.source == EvidenceSource.OCR]
        asr = [e for e in texts if e.source == EvidenceSource.ASR]

        findings: list[MandatoryFinding] = []
        for req in self.requirements:
            if not req.applies_to(industry):
                continue

            ocr_hits = [e for e in ocr if self._text_hits(req, e.text)]
            if ocr_hits:
                # 同一条提示语可能出现多次。只要**有一次**是显著的就算达标，
                # 所以取表现最好的那次：先看通过项多少，再看持续时长。
                scored = [(self.measure_salience(req, e), e) for e in ocr_hits]
                measures, ev = max(
                    scored, key=lambda t: (sum(m.passed for m in t[0]), t[1].duration)
                )
                status = (
                    MandatoryStatus.OK
                    if all(m.passed for m in measures)
                    else MandatoryStatus.NOT_SALIENT
                )
                findings.append(MandatoryFinding(req, status, ev, measures))
                continue

            asr_hits = [e for e in asr if self._text_hits(req, e.text)]
            if asr_hits:
                # 口播说了但画面没标。「显著标明」通常指向视觉呈现，
                # 但纯口播是否满足要求存在解释空间 —— 交人工判断，不自行定性。
                findings.append(
                    MandatoryFinding(req, MandatoryStatus.SPOKEN_ONLY, asr_hits[0], [])
                )
                continue

            findings.append(MandatoryFinding(req, MandatoryStatus.MISSING))

        risky = [f for f in findings if f.counts_as_risk]
        advisory = [f for f in findings if f.is_risk and not f.counts_as_risk]
        logger.info(
            "必备要素核查：适用 %d 项，风险 %d 项，仅提示 %d 项（行业=%s）",
            len(findings), len(risky), len(advisory), industry or "通用",
        )
        return findings


def load_default_checker() -> MandatoryChecker:
    return MandatoryChecker()
