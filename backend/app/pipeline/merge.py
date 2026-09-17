"""字幕跨帧合并：把逐帧 OCR 结果还原成「一条花字从第几秒到第几秒」。

为什么必须有这一步：

OCR 是按帧跑的，同一条花字在画面上停留 3 秒，就会在多个代表帧里各出现一次。
不合并的话，报告里会出现十几条内容重复、时间区间各自只有零点几秒的风险，
而且 **L4 显著性判定会彻底失效** —— 「这条免责声明只显示了 0.4 秒」
这个结论的前提，正是先把同一条文字的所有出现合并起来算出真实总时长。

合并条件必须是**三重**的，少一条都会错：

    文本相似  只看它 → 画面上方「全网销量第一」和下方「限时特惠第一」会被并成一条
    空间重叠  只看它 → 同一位置先后出现的两条不同文案会被并成一条
    时间邻接  只看它 → 视频开头和结尾各出现一次的同一句话会被并成一条
                       （那其实是两次独立出现，报告里该分别标注）

参考了 video-subtitle-extractor（Apache-2.0）的相似度合并思路，
但它假设字幕固定在画面下方——这个前提对广告不成立，广告花字满屏乱飞，
所以这里改成全帧 OCR + 空间 IoU 双条件。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.config import PipelineSettings, get_settings
from app.pipeline.evidence import BBox, EvidenceSource, TextEvidence

logger = logging.getLogger(__name__)

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    """归一化：去掉所有空白。

    不做去标点：广告花字里的「！」「，」有时正是断句依据，
    去掉反而会让两条不同文案看起来更像。
    """
    return _WS.sub("", s)


def _text_match(a: str, b: str, threshold: float) -> bool:
    """两段文字是不是同一条花字的两次识别。

    除了模糊相似度，还额外接受**包含关系** —— 花字淡入淡出时，
    边缘帧常只识别出一部分（「本品不能代」之于「本品不能代替药物」）。
    但包含关系要设下限，否则「的」会匹配上任何句子。
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True

    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 2 and short in long_ and len(short) / len(long_) >= 0.4:
        return True

    return fuzz.ratio(na, nb) / 100.0 >= threshold


@dataclass
class _Track:
    """一条正在延续中的花字。"""

    members: list[TextEvidence] = field(default_factory=list)

    @property
    def last(self) -> TextEvidence:
        return self.members[-1]

    @property
    def t_end(self) -> float:
        return max(m.t_end for m in self.members)

    @property
    def frame_ids(self) -> set[int]:
        return {fid for m in self.members for fid in m.frame_ids}

    def accepts(self, ev: TextEvidence, cfg: PipelineSettings) -> bool:
        # 同一帧内的两个文本块永远是画面上不同的两处，绝不合并
        if self.frame_ids & set(ev.frame_ids):
            return False
        # 时间必须邻接：间隔太久说明是两次独立出现
        if ev.t_start - self.t_end > cfg.merge_max_gap_seconds:
            return False
        if not _text_match(self.last.text, ev.text, cfg.merge_text_similarity):
            return False
        # 空间必须重叠（两边都得有 bbox 才谈得上比）
        if self.last.bbox is None or ev.bbox is None:
            return False
        return self.last.bbox.iou(ev.bbox) >= cfg.merge_bbox_iou

    def collapse(self) -> TextEvidence:
        """把整条轨迹压成一条证据。"""
        rep = _representative(self.members)
        font_scales = sorted(m.font_scale for m in self.members if m.font_scale is not None)
        median = font_scales[len(font_scales) // 2] if font_scales else rep.font_scale

        return TextEvidence(
            id=rep.id,
            source=rep.source,
            text=rep.text,
            t_start=min(m.t_start for m in self.members),
            t_end=self.t_end,
            bbox=rep.bbox,
            # 字号取中位数而非代表帧的值：淡入淡出时边缘帧的框会偏小，
            # 用它判显著性会冤枉本来合规的素材。
            font_scale=median,
            # None 表示来源没给置信度，不能当 0 参与比较，也不能凭空当 1.0。
            # 全员都是 None 时结果仍为 None —— 如实保留「未知」。
            confidence=max((m.confidence for m in self.members if m.confidence is not None),
                           default=None),
            frame_ids=sorted(self.frame_ids),
            provider=rep.provider,
            provider_version=rep.provider_version,
            raw_ref=rep.raw_ref,
        )


def _representative(members: list[TextEvidence]) -> TextEvidence:
    """挑一条最可信的识别结果作为这条花字的正式文本。

    优先取**众数**：同一条文字被正确识别的次数通常多于被识别错的次数，
    这比「取置信度最高」更抗个别帧的抖动。众数并列时取更长的
    （淡入帧只识别出片段，完整的那条更长），再并列才看置信度。
    """
    counts = Counter(_norm(m.text) for m in members)
    top = max(counts.values())
    finalists = [m for m in members if counts[_norm(m.text)] == top]
    return max(finalists, key=lambda m: (len(_norm(m.text)), m.confidence or 0.0))


def merge_ocr(
    evidences: list[TextEvidence], cfg: PipelineSettings | None = None
) -> list[TextEvidence]:
    """合并画面文字证据。只处理 OCR，ASR 原样返回。

    ASR 不参与合并：语音是连续流，provider 切出的句子本就该保持独立，
    合并会破坏字级时间戳与文本的对应关系。
    """
    cfg = cfg or get_settings().pipeline

    ocr = sorted(
        (e for e in evidences if e.source == EvidenceSource.OCR),
        key=lambda e: (e.t_start, e.bbox.y if e.bbox else 0.0),
    )
    others = [e for e in evidences if e.source != EvidenceSource.OCR]

    open_tracks: list[_Track] = []
    closed: list[_Track] = []

    for ev in ocr:
        # 先把已经断开太久的轨迹归档，避免后面误接上
        still_open = []
        for t in open_tracks:
            (still_open if ev.t_start - t.t_end <= cfg.merge_max_gap_seconds else closed).append(t)
        open_tracks = still_open

        # 在所有候选里挑空间重叠最大的那条，而不是遇到第一条就接上 ——
        # 画面上同时有两条位置相近的花字时，接错了会串台
        best, best_iou = None, -1.0
        for t in open_tracks:
            if t.accepts(ev, cfg):
                iou = t.last.bbox.iou(ev.bbox) if (t.last.bbox and ev.bbox) else 0.0
                if iou > best_iou:
                    best, best_iou = t, iou

        if best is not None:
            best.members.append(ev)
        else:
            open_tracks.append(_Track([ev]))

    merged = [t.collapse() for t in closed + open_tracks]
    merged.sort(key=lambda e: (e.t_start, e.bbox.y if e.bbox else 0.0))

    if ocr:
        logger.info(
            "字幕合并：%d 条逐帧结果 → %d 条花字（平均每条跨 %.1f 帧）",
            len(ocr), len(merged), len(ocr) / max(len(merged), 1),
        )
    return others + merged


def merge_bundle(bundle, cfg: PipelineSettings | None = None):
    """就地合并一个证据包里的 OCR 证据。"""
    bundle.evidences = merge_ocr(list(bundle.evidences), cfg)
    return bundle
