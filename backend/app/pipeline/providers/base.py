"""Provider 抽象层 —— 「商用留口」的落地处。

云 API 与本地模型各自实现同一组接口。今天没 GPU 走云，
将来换 FunASR / PaddleOCR / Tarsier2 只改 .env 的 *_PROVIDER，业务代码一行不改。

两个设计要点：

1. **能力声明（Capabilities）**：ASR 是否支持字级时间戳是硬指标。
   与其等到跑完发现时间戳是段级的、报告里所有秒数都不可用，
   不如在初始化时就把不合格的 provider 拦下来。

2. **成本闸门放在基类**：OCR/VLM 调用次数红线用模板方法在基类里守，
   子类实现 `_recognize_impl`，拿不到绕过闸门的机会。
   放在调用方守是守不住的 —— 总会有人忘。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.pipeline.evidence import BBox, TextEvidence, VisualEntityEvidence

if TYPE_CHECKING:
    from app.pipeline.frames import SampledFrame

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    pass


class CapabilityError(ProviderError):
    """Provider 不满足硬性能力要求。初始化即失败，不允许带病上路。"""


class CostLimitExceeded(ProviderError):
    """超出成本红线。**刻意抛错而不是静默截断** ——
    静默截断会让报告看起来"审完了"，实际后半段视频根本没看，这比报错危险得多。"""


# ──────────────────────────────────────────────────────────────
#  能力声明
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ASRCapabilities:
    word_timestamps: bool
    """字/词级时间戳。**硬指标**，False 直接拒绝使用。

    没有它只能定位到「这句话大概在 12-15 秒」，
    而产品承诺的是「『国家级』这三个字在 13.4 秒」。"""

    punctuation: bool = False
    hotwords: bool = False
    """热词定制。行业术语（如药品名、品牌名）识别率靠它，非硬指标但影响很大。"""


@dataclass(frozen=True)
class OCRCapabilities:
    bbox: bool
    """是否返回文字框坐标。**硬指标** —— L4 显著性核查
    （「字号只占 2%」「藏在右下角」）完全依赖 bbox，拿不到就做不了。"""

    confidence: bool = False


# ──────────────────────────────────────────────────────────────
#  工具
# ──────────────────────────────────────────────────────────────


def to_normalized_bbox(
    x: float, y: float, w: float, h: float, img_w: int, img_h: int
) -> BBox:
    """像素坐标 → 归一化坐标，并夹紧到 [0,1]。

    夹紧是必要的：部分 OCR 会返回略微越界的框（如 x=-2），
    直接构造 BBox 会被 pydantic 拒绝，让整条视频失败 —— 不值得。
    """
    if img_w <= 0 or img_h <= 0:
        raise ValueError(f"非法图像尺寸 {img_w}x{img_h}")

    nx = min(max(x / img_w, 0.0), 1.0)
    ny = min(max(y / img_h, 0.0), 1.0)
    nw = min(max(w / img_w, 1e-6), 1.0 - nx)
    nh = min(max(h / img_h, 1e-6), 1.0 - ny)
    return BBox(x=nx, y=ny, w=nw, h=nh)


def font_scale_from_bbox(bbox: BBox) -> float:
    """文字高度占画面高度的比例。L4 显著性判定的输入之一。"""
    return bbox.h


def ocr_budget_for(duration_seconds: float, base: int,
                   calibrated_for_seconds: float = 30.0) -> int:
    """按时长换算 OCR 成本红线。

    原来的红线是一个固定值（20 次），但它是**按 30 秒广告标定**的。
    直接拿去卡 60 秒素材，等于要求后者的去重率是前者的两倍——
    这不是成本要求，是长度歧视，只会逼人去调大常量了事（那就等于没有红线）。

    所以改成保持**每秒成本**恒定：20 次 / 30 秒 ≈ 0.67 次/秒。
    短于标定时长的仍按 base 走，避免几秒的素材被卡到不合理的低值。

    ⚠️ 放宽的是长度带来的差异，**不是成本本身**。快切素材（本项目实测
    一条 54 秒广告有 36 个镜头切换、去重率仅 31%）照样会触发红线——
    那是真的贵，就该停下来让人确认，而不是静默烧钱。
    """
    if duration_seconds <= 0 or calibrated_for_seconds <= 0:
        return base
    import math
    return max(base, math.ceil(duration_seconds * base / calibrated_for_seconds))


# ──────────────────────────────────────────────────────────────
#  ASR
# ──────────────────────────────────────────────────────────────


class ASRProvider(ABC):
    name: str = "abstract"

    def __init__(self) -> None:
        caps = self.capabilities()
        if not caps.word_timestamps:
            raise CapabilityError(
                f"ASR provider「{self.name}」不支持字级时间戳，拒绝使用。\n"
                "字级时间戳是硬指标：没有它只能定位到句子，无法定位到词，"
                "报告里「第 13.4 秒说了国家级」这类结论就无从谈起。\n"
                "请改用支持 word-level timestamp 的供应商，"
                "或本地部署 FunASR/Paraformer-large（原生支持）。"
            )

    @abstractmethod
    def capabilities(self) -> ASRCapabilities: ...

    @abstractmethod
    def transcribe(self, audio_path: Path, hotwords: list[str] | None = None) -> list[TextEvidence]:
        """音频 → 带字级时间戳的文本证据。

        实现约定：
          - source 必须是 EvidenceSource.ASR
          - word_timings 必须非空且覆盖 text 的全部字符（否则 offset 换算会退化）
          - bbox / font_scale 恒为 None（语音没有空间位置）
        """


# ──────────────────────────────────────────────────────────────
#  OCR
# ──────────────────────────────────────────────────────────────


class OCRProvider(ABC):
    name: str = "abstract"

    def __init__(self, max_calls: int) -> None:
        caps = self.capabilities()
        if not caps.bbox:
            raise CapabilityError(
                f"OCR provider「{self.name}」不返回文字框坐标，拒绝使用。\n"
                "bbox 是硬指标：L4 必备要素显著性核查"
                "（免责声明字号是否过小、是否藏在角落）完全依赖它，"
                "而这正是本产品相对文本审核工具的核心差异化能力。"
            )
        self.max_calls = max_calls
        self._calls = 0

    @property
    def calls_used(self) -> int:
        return self._calls

    @abstractmethod
    def capabilities(self) -> OCRCapabilities: ...

    @abstractmethod
    def _recognize_impl(self, frame: SampledFrame, img_w: int, img_h: int) -> list[TextEvidence]:
        """识别单帧。子类只实现这个，成本闸门由基类守。"""

    def recognize(self, frames: list[SampledFrame], img_w: int, img_h: int) -> list[TextEvidence]:
        """批量识别。超过成本红线直接抛错，不静默截断。"""
        if len(frames) > self.max_calls:
            raise CostLimitExceeded(
                f"需 OCR {len(frames)} 帧，超过单条视频上限 {self.max_calls} 帧。\n"
                "这说明帧去重没达标（目标削减 ≥70%）。请检查：\n"
                "  1. pipeline.phash_hamming_threshold 是否过小（去重太保守）\n"
                "  2. 素材是否为持续运动画面（此类素材本身难去重）\n"
                "  3. 视频是否过长\n"
                "**不要直接调大 max_ocr_calls_per_video 了事** —— 那是把成本问题藏起来。"
            )

        out: list[TextEvidence] = []
        for frame in frames:
            self._calls += 1
            evidences = self._recognize_impl(frame, img_w, img_h)
            # 用代表帧折叠出来的时间跨度覆盖单帧时刻。
            # 这一步很关键：去重时被丢掉的重复帧，其时长信息就存在 span 里，
            # 不回填的话报告里的时间区间会缩成一个点，L4 时长判定也会失效。
            for ev in evidences:
                ev.t_start = frame.span_start
                ev.t_end = max(frame.span_end, frame.span_start)
                ev.frame_ids = [frame.frame_id]
            out.extend(evidences)
        return out


# ──────────────────────────────────────────────────────────────
#  VLM
# ──────────────────────────────────────────────────────────────


class VLMProvider(ABC):
    """视觉巡检：识别画面里的 IP 形象 / logo / 肖像。

    ⚠️ 实现必须遵守两条，否则 IP 误报会失控：
      1. prompt 必须提供「无 / 不确定」选项，不能逼模型二选一
      2. 产出的 VisualEntityEvidence 一律 needs_human_review=True
         —— VLM 是兜底层，它单独说的话不算数，要底库交叉验证过才算
    """

    name: str = "abstract"

    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self._calls = 0

    @property
    def calls_used(self) -> int:
        return self._calls

    @abstractmethod
    def _scan_impl(self, frames: list[SampledFrame]) -> list[VisualEntityEvidence]:
        """扫描一批帧（支持多图批量输入以压低调用次数）。"""

    def scan(self, frames: list[SampledFrame], batch_size: int = 4) -> list[VisualEntityEvidence]:
        batches = [frames[i : i + batch_size] for i in range(0, len(frames), batch_size)]
        if len(batches) > self.max_calls:
            raise CostLimitExceeded(
                f"需 VLM 调用 {len(batches)} 次（{len(frames)} 帧 / 每批 {batch_size}），"
                f"超过单条视频上限 {self.max_calls} 次。\n"
                "VLM 只应扫**场景关键帧**（IP 形象通常持续数秒，不需要 2fps 那么密），"
                "且底库已命中的帧不必再问 VLM。"
            )

        out: list[VisualEntityEvidence] = []
        for batch in batches:
            self._calls += 1
            results = self._scan_impl(batch)
            for ev in results:
                # 强制标记：VLM 单独发现的一律待人工确认，不进正式风险清单。
                # 理由是 VLM 会幻觉，把普通老鼠说成米奇；而 IP 误报的代价很高 ——
                # 会让法务白跑一趟去要一份根本不需要的授权书。
                ev.needs_human_review = True
            out.extend(results)
        return out
