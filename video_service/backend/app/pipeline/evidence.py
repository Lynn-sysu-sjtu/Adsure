"""证据单元 —— 整个系统的枢纽数据结构。

取证层（ASR / OCR / VLM / IP 底库）的唯一出口，找法层的唯一入口。

设计目标只有一个：**任何一条风险都能精确回答「第几秒、画面哪个位置、凭哪一帧」**。
没有这个，报告就退化成"你的视频里有违禁词"，跟现有文本工具没区别。

两种证据：
  - TextEvidence         口播 / 画面文字 → 交给违禁词库
  - VisualEntityEvidence 画面里的 IP 形象 / logo → 交给 IP 规则

字符 offset → 时间戳的映射见 `TextEvidence.resolve_time()` 与 `TranscriptIndex`，
这是"定位到第 13.4 秒"能否成立的关键机制。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class EvidenceSource(StrEnum):
    ASR = "asr"
    OCR = "ocr"
    VLM = "vlm"
    IP_MATCH = "ip_match"


class EntityType(StrEnum):
    CARTOON_CHARACTER = "cartoon_character"
    BRAND_LOGO = "brand_logo"
    CELEBRITY = "celebrity"
    ARTWORK = "artwork"
    ARCHITECTURE = "architecture"
    FONT = "font"  # 商用字体，二期
    OTHER = "other"


class BBox(BaseModel):
    """归一化边界框，取值 [0, 1]，原点在左上角。

    用归一化而非像素坐标，因为同一条视频可能在不同分辨率下被处理，
    而「字号占画面比例」「是否在角落」这类显著性判断本来就是相对量。
    """

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2, self.y + self.h / 2)

    def iou(self, other: BBox) -> float:
        """交并比。用于字幕跨帧合并时判断「是不是同一处文字」。"""
        ix0, iy0 = max(self.x, other.x), max(self.y, other.y)
        ix1 = min(self.x + self.w, other.x + other.w)
        iy1 = min(self.y + self.h, other.y + other.h)
        if ix1 <= ix0 or iy1 <= iy0:
            return 0.0
        inter = (ix1 - ix0) * (iy1 - iy0)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def near_edge(self, margin: float) -> bool:
        """是否贴边（「藏在角落」的判定依据之一）。"""
        return (
            self.x < margin
            or self.y < margin
            or (self.x + self.w) > (1.0 - margin)
            or (self.y + self.h) > (1.0 - margin)
        )


class WordTiming(BaseModel):
    """字/词级时间戳。

    ⚠️ 这是 ASR 选型的硬指标。没有它，就只能定位到「这句话大概在 12-15 秒」，
    而产品承诺的是「'国家级'这三个字在 13.4 秒」。段级时间戳不满足要求。
    """

    text: str
    t_start: float
    t_end: float


class _EvidenceBase(BaseModel):
    id: str
    source: EvidenceSource
    t_start: float = Field(ge=0.0)
    t_end: float = Field(ge=0.0)

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """识别置信度。**None 表示来源未给出**，不等于「有把握」。

    刻意不默认成 1.0：那等于替 provider 声称了它从没声称过的确定性，
    在一份要给法务看的证据里，这是编造数据质量。"""

    frame_ids: list[int] = Field(default_factory=list)
    """溯源到具体帧号，报告里据此出证据截图。ASR 证据可为空。"""

    frame_labels: list[str] = Field(default_factory=list)
    """导入外部 evidence 时保留原始帧标签，保证往返不改变补零宽度。"""

    # ── 取证链 ──────────────────────────────────────────────
    # 报告说「第 28 秒画面右下角有行小字」，法务要能追问两件事：
    # 这是哪个引擎认出来的？原图在哪？答不上来，这条证据就不可采信。
    # 字段设计对齐团队既有的 video-mvp-evidence/v1，两边可互读。
    provider: str | None = None
    """产出该条证据的服务或模型标识，如 "Apple Vision/VNRecognizeTextRequest"。"""

    provider_version: str | None = None

    raw_ref: dict = Field(default_factory=dict)
    """指回原始产物的引用，如 {"frame_path": "frames/frame_000002.jpg"}。"""

    @model_validator(mode="after")
    def _check_interval(self):
        if self.t_end < self.t_start:
            raise ValueError(f"t_end({self.t_end}) < t_start({self.t_start})")
        return self

    @property
    def duration(self) -> float:
        return self.t_end - self.t_start


class TextEvidence(_EvidenceBase):
    """文本证据：口播（ASR）或画面文字（OCR）。"""

    kind: Literal["text"] = "text"
    text: str

    bbox: BBox | None = None
    """OCR 独有。ASR 没有空间位置，为 None。"""

    font_scale: float | None = None
    """文字高度占画面高度的比例。判断「字号是否显著」用，OCR 独有。"""

    word_timings: list[WordTiming] = Field(default_factory=list)
    """字/词级时间戳。ASR 有；OCR 没有（整块文字共享一个时间区间）。"""

    def resolve_time(self, char_start: int, char_end: int) -> tuple[float, float]:
        """把命中词在本条证据内的字符区间，换算成精确时间区间。

        这是「AC 自动机命中 → 第 13.4 秒」这条链路的关键一步。

        - 有 word_timings（ASR）：按字符游标走到对应的词，取其时间边界 → 精确到词
        - 无 word_timings（OCR）：整块文字共用一个时间区间 → 返回本条的 t_start/t_end

        char_end 为**开区间**上界，与 str 切片语义一致。
        """
        if not self.word_timings:
            return self.t_start, self.t_end

        cursor = 0
        hit_start: float | None = None
        hit_end: float | None = None
        for wt in self.word_timings:
            w_lo, w_hi = cursor, cursor + len(wt.text)
            # 该词与命中区间有交叠
            if w_lo < char_end and w_hi > char_start:
                if hit_start is None:
                    hit_start = wt.t_start
                hit_end = wt.t_end
            cursor = w_hi

        if hit_start is None or hit_end is None:
            # 落在 word_timings 覆盖不到的位置（如拼接时插入的分隔符），退回整条区间
            return self.t_start, self.t_end
        return hit_start, hit_end


class VisualEntityEvidence(_EvidenceBase):
    """视觉实体证据：画面里出现的 IP 形象 / logo / 肖像。

    ⚠️ 本类只陈述「画面里出现了什么」，**不做侵权定性**。
    识别出米奇 ≠ 侵权（可能有授权、可能合理使用）。
    定性由找法/用法层完成，且产出的是「需核验的授权材料清单」而非「侵权认定」。
    """

    kind: Literal["visual_entity"] = "visual_entity"

    entity_name: str
    entity_type: EntityType
    rights_holder: str | None = None

    bbox: BBox | None = None

    ip_id: str | None = None
    """命中的底库条目 id（对应 ip_registry.yaml）。VLM 发现的长尾 IP 可能为 None。"""

    match_ref: str | None = None
    """底库里匹配到的具体参考图。这是**可呈堂的证据**——
    VLM 那句"我觉得像米奇"不是，底库比对的"与 mickey_003.jpg 相似度 0.91"才是。"""

    needs_human_review: bool = False
    """仅 VLM 单独命中（底库未命中）时置 True。

    这类结果**不进正式风险清单**，只标"疑似待人工确认"。
    理由：VLM 会幻觉，把普通老鼠说成米奇。IP 误报的代价很高——
    会让法务白跑一趟去要一份根本不需要的授权书，信任一次就崩。"""


Evidence = Annotated[TextEvidence | VisualEntityEvidence, Field(discriminator="kind")]


class CostRecord(BaseModel):
    """成本埋点。每条视频记录实际调用次数，用于验证成本红线是否守住。

    方案里 OCR ≤20 次、VLM ≤4 次是硬红线，没有埋点就无从验证。
    """

    asr_calls: int = 0
    ocr_calls: int = 0
    vlm_calls: int = 0
    ip_index_queries: int = 0
    llm_calls: int = 0

    frames_sampled: int = 0
    frames_after_dedup: int = 0

    @property
    def dedup_ratio(self) -> float:
        """帧去重削减率。方案目标 ≥0.70，达不到 OCR 成本会失控。"""
        if self.frames_sampled == 0:
            return 0.0
        return 1.0 - self.frames_after_dedup / self.frames_sampled


class VideoMeta(BaseModel):
    path: str
    duration: float
    fps: float = 0.0
    width: int = 0
    height: int = 0
    """0 表示来源未提供。video-mvp 的 manifest 只记时长和帧数，不含分辨率；
    由于 bbox 已归一化，缺分辨率不影响分析，只影响换算回像素坐标。"""

    has_audio: bool = True


class EvidenceBundle(BaseModel):
    """一条视频的全部证据。取证层的最终产物，直接喂给找法层。"""

    review_id: str
    video: VideoMeta
    evidences: list[Evidence] = Field(default_factory=list)
    cost: CostRecord = Field(default_factory=CostRecord)

    def texts(self, source: EvidenceSource | None = None) -> list[TextEvidence]:
        return [
            e
            for e in self.evidences
            if isinstance(e, TextEvidence) and (source is None or e.source == source)
        ]

    def visual_entities(self) -> list[VisualEntityEvidence]:
        return [e for e in self.evidences if isinstance(e, VisualEntityEvidence)]


class TranscriptIndex:
    """把多条文本证据拼成一篇可整体匹配的文档，并支持 offset 反查。

    为什么需要它：**ASR 和 OCR 的匹配语义不一样**。

    - ASR 是连续语流。provider 切出的"句子"只是它的分段产物，不是真实语义边界，
      违禁词完全可能横跨两句（"……本品是国家" + "级配方……"）。
      所以必须**无分隔符**拼接后整体匹配 —— 说话人确实连续说出了这几个字。
    - OCR 每块文字是画面上彼此独立的一处，拼接会造出现实中不存在的词
      （画面上方"全网第一" + 下方"品牌直供" ≠ "第一品牌"）。
      所以 OCR 必须逐条匹配，根本不该走这个类。

    `separator` 默认为空串正是为了 ASR 的跨句匹配。若某个场景确实需要
    阻断跨条匹配，传入 "\\x00" 之类不可能出现在正文里的字符即可。
    """

    def __init__(self, units: list[TextEvidence], join_all: bool = True, separator: str = ""):
        self.units = units
        self.join_all = join_all
        self.separator = separator
        self._spans: list[tuple[int, int, TextEvidence]] = []

        if join_all:
            parts: list[str] = []
            cursor = 0
            for i, u in enumerate(units):
                start = cursor
                parts.append(u.text)
                cursor += len(u.text)
                self._spans.append((start, cursor, u))
                if separator and i < len(units) - 1:
                    parts.append(separator)
                    cursor += len(separator)
            self.document = "".join(parts)
        else:
            self.document = ""

    def _unit_at(self, offset: int) -> tuple[TextEvidence, int] | None:
        """全局 offset → (所属证据, 条内 offset)。落在分隔符上返回 None。"""
        for start, end, unit in self._spans:
            if start <= offset < end:
                return unit, offset - start
        return None

    def locate(self, global_start: int, global_end: int) -> tuple[TextEvidence, int, int] | None:
        """把文档全局 offset 换算成 (所属证据, 条内起始, 条内结束)。

        命中横跨两条证据时归属到**起始**那条，条内结束 offset 夹到该条末尾。
        """
        located = self._unit_at(global_start)
        if located is None:
            return None
        unit, local_start = located
        local_end = min(global_end - global_start + local_start, len(unit.text))
        return unit, local_start, local_end

    def resolve(self, global_start: int, global_end: int) -> tuple[TextEvidence, float, float] | None:
        """一步到位：文档 offset → (起始证据, t_start, t_end)。

        ⚠️ 命中横跨两条证据时，**起止时间必须分别取自两条**：
        起点来自命中开始所在的那条，终点来自命中结束所在的那条。
        只用起始条会让跨句命中的结束时间偏早，报告里的时间区间就是错的。
        """
        start_loc = self._unit_at(global_start)
        if start_loc is None:
            return None
        start_unit, s_local = start_loc
        t0, _ = start_unit.resolve_time(s_local, s_local + 1)

        # 用 global_end - 1 定位最后一个字符所在的证据
        end_loc = self._unit_at(max(global_start, global_end - 1))
        if end_loc is None:
            # 命中末端落在分隔符上，退回起始条的边界
            _, t1 = start_unit.resolve_time(s_local, len(start_unit.text))
        else:
            end_unit, e_local = end_loc
            _, t1 = end_unit.resolve_time(e_local, e_local + 1)

        return start_unit, t0, max(t0, t1)
