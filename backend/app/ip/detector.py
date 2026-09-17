# -*- coding: utf-8 -*-
"""双层 IP 检测与融合（实施方案 v2 第五节）。

调用顺序刻意为「先底库、后 VLM」：
  1. 每帧走 SSCD 特征 + 本地向量检索，零成本且证据可呈堂（与 mickey_003.jpg 相似度 0.91）
  2. 底库已命中的帧不再问 VLM —— 把 VLM 调用压到 2–4 次/条
  3. 仅 VLM 命中 → ReviewStatus.SUSPECTED_PENDING，**模型层强制**，构造方无法绕过

输出是 IPHit（带授权材料清单），不是侵权结论。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ip.library import IPLibrary
from app.ip.schema import IPLibraryEntry
from app.ip.vectors import FrameEmbedder, PurePythonVectorIndex, SearchHit
from app.pipeline.evidence import (
    BBox,
    EntityType,
    EvidenceSource,
    VisualEntityEvidence,
)
from app.pipeline.frames import SampledFrame
from app.pipeline.providers.base import VLMProvider

logger = logging.getLogger(__name__)


class HitSource(StrEnum):
    LIBRARY = "library"
    VLM = "vlm"


class ReviewStatus(StrEnum):
    CONFIRMED = "confirmed"
    """底库命中（含双层都中），进正式风险清单。"""

    SUSPECTED_PENDING = "suspected_pending"
    """仅 VLM 命中，待人工确认，不进正式清单。"""


class IPHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    ip_id: str | None
    entity_name: str
    entity_type: EntityType
    sources: frozenset[HitSource]
    review_status: ReviewStatus

    t_start: float
    t_end: float
    frame_ids: list[int] = Field(default_factory=list)
    bbox: BBox | None = None

    score: float | None = None
    match_ref: str | None = None
    rights_holder: str | None = None
    required_materials: tuple[str, ...] = ()
    uncertainty: bool = False

    @model_validator(mode="before")
    @classmethod
    def _force_review_status(cls, data: object) -> object:
        """关键不变式（方案「代码里已防住的坑」#6）：

        仅 VLM 命中的条目一律 suspected_pending —— 不管调用方传了什么。
        放在模型入口做强制，子类/工厂/直接构造都绕不过。
        """
        if isinstance(data, dict):
            sources = data.get("sources") or set()
            sources = {HitSource(s) for s in sources}
            data = dict(data)
            data["sources"] = frozenset(sources)
            if HitSource.VLM in sources and HitSource.LIBRARY not in sources:
                data["review_status"] = ReviewStatus.SUSPECTED_PENDING
            else:
                data["review_status"] = ReviewStatus.CONFIRMED
        return data

    @property
    def is_pending(self) -> bool:
        return self.review_status is ReviewStatus.SUSPECTED_PENDING

    def to_evidence(self) -> VisualEntityEvidence:
        return VisualEntityEvidence(
            id=f"ip_{self.frame_ids[0] if self.frame_ids else 0}_{self.ip_id or 'x'}",
            source=EvidenceSource.VLM if self.is_pending else EvidenceSource.IP_MATCH,
            entity_name=self.entity_name,
            entity_type=self.entity_type,
            rights_holder=self.rights_holder,
            t_start=self.t_start,
            t_end=self.t_end,
            bbox=self.bbox,
            ip_id=self.ip_id,
            match_ref=self.match_ref,
            confidence=self.score,
            frame_ids=list(self.frame_ids),
            needs_human_review=self.is_pending,
        )


@dataclass
class DetectionResult:
    hits: list[IPHit]

    @property
    def confirmed(self) -> list[IPHit]:
        return [h for h in self.hits if not h.is_pending]

    @property
    def pending(self) -> list[IPHit]:
        return [h for h in self.hits if h.is_pending]


class IPDetector:
    """底库检索 → VLM 兜底 → 融合。"""

    def __init__(
        self,
        library: IPLibrary,
        index: PurePythonVectorIndex,
        embedder: FrameEmbedder | None = None,
        vlm: VLMProvider | None = None,
        confirm_threshold: float = 0.85,
    ) -> None:
        self.library = library
        self.index = index
        self.embedder = embedder
        self.vlm = vlm
        self.confirm_threshold = confirm_threshold
        if embedder is not None and embedder.dim != index.dim:
            raise ValueError(
                f"embedder 维度 {embedder.dim} 与索引维度 {index.dim} 不一致"
            )

    @property
    def library_active(self) -> bool:
        return self.embedder is not None and len(self.index) > 0

    def detect(self, frames: Sequence[SampledFrame]) -> DetectionResult:
        frames = list(frames)
        hits: list[IPHit] = []

        # ── 第 1 层：底库 SSCD 检索（CPU，成本为零，证据可呈堂）────────
        library_hit_frames: set[int] = set()
        if self.library_active:
            vectors = self.embedder.embed_frames(frames)  # type: ignore[union-attr]
            for frame, vec in zip(frames, vectors):
                top = self.index.search(vec, k=1)
                if not top or top[0].score < self.confirm_threshold:
                    continue
                hit = top[0]
                entry = self.library.get(hit.ip_id)
                if entry is None:
                    # 索引指向库里已删除的条目：宁可不报，也不能凭 ip_id 编材料
                    logger.warning("向量索引命中未知 ip_id=%s，已跳过", hit.ip_id)
                    continue
                library_hit_frames.add(frame.frame_id)
                hits.append(self._library_hit(frame, hit, entry))

        # ── 第 2 层：VLM 只扫底库没挡住的帧（成本闸门在 VLMProvider 基类）─
        remaining = [f for f in frames if f.frame_id not in library_hit_frames]
        if self.vlm is not None and remaining:
            for ev in self.vlm.scan(remaining):
                if not ev.frame_ids:
                    continue
                hits.append(self._vlm_hit(ev))

        return DetectionResult(hits=consolidate_hits(hits))

    def _library_hit(
        self, frame: SampledFrame, hit: SearchHit, entry: IPLibraryEntry
    ) -> IPHit:
        return IPHit(
            ip_id=entry.ip_id,
            entity_name=entry.name_cn,
            entity_type=EntityType.OTHER,
            sources=frozenset({HitSource.LIBRARY}),
            review_status=ReviewStatus.CONFIRMED,
            t_start=frame.span_start,
            t_end=max(frame.span_end, frame.span_start),
            frame_ids=[frame.frame_id],
            score=hit.score,
            match_ref=hit.ref_name,
            rights_holder=entry.rights_holder,
            required_materials=tuple(entry.required_materials),
        )

    def _vlm_hit(self, ev: VisualEntityEvidence) -> IPHit:
        entry = None
        if ev.ip_id:
            entry = self.library.get(ev.ip_id)
        if entry is None and ev.entity_name:
            entry = self.library.match_by_name(ev.entity_name)
        fid = ev.frame_ids[0]
        return IPHit(
            ip_id=entry.ip_id if entry else (ev.ip_id or None),
            entity_name=entry.name_cn if entry else ev.entity_name,
            entity_type=ev.entity_type,
            sources=frozenset({HitSource.VLM}),
            # review_status 不用调用方操心：模型校验器对 VLM-only 强制 pending
            review_status=ReviewStatus.CONFIRMED,
            t_start=ev.t_start,
            t_end=ev.t_end,
            frame_ids=[fid, *ev.frame_ids[1:]],
            bbox=ev.bbox,
            score=ev.confidence,
            rights_holder=entry.rights_holder if entry else ev.rights_holder,
            required_materials=tuple(entry.required_materials) if entry else (),
        )


def consolidate_hits(hits: Sequence[IPHit], max_gap_seconds: float = 1.5) -> list[IPHit]:
    """把同一 IP 相邻帧的命中合并成时间区间（IP 时间区间误差指标需要 span）。

    只合同名同 ip_id 的条目；合并后 sources 取并集 —— 因此「同一区间内
    底库与 VLM 都命中」自然升级为 confirmed（双层交叉验证）。
    """
    groups: list[list[IPHit]] = []
    for h in sorted(hits, key=lambda x: x.t_start):
        key = (h.ip_id or f"name:{h.entity_name}")
        for group in groups:
            g = group[-1]
            gkey = g.ip_id or f"name:{g.entity_name}"
            if gkey == key and h.t_start <= g.t_end + max_gap_seconds:
                group.append(h)
                break
        else:
            groups.append([h])

    out: list[IPHit] = []
    for group in groups:
        if len(group) == 1:
            out.append(group[0])
            continue
        sources = frozenset().union(*(h.sources for h in group))
        frame_ids = sorted({fid for h in group for fid in h.frame_ids})
        first, last = group[0], group[-1]
        # 区间内以底库证据为准（可呈堂），分数字段取最高
        lib = next((h for h in group if HitSource.LIBRARY in h.sources), first)
        out.append(IPHit(
            ip_id=first.ip_id,
            entity_name=first.entity_name,
            entity_type=first.entity_type,
            sources=sources,
            review_status=ReviewStatus.CONFIRMED,  # 由模型按 sources 重新裁决
            t_start=min(h.t_start for h in group),
            t_end=max(h.t_end for h in group),
            frame_ids=frame_ids,
            bbox=lib.bbox or first.bbox,
            score=max((h.score or 0.0) for h in group) or None,
            match_ref=next((h.match_ref for h in group if h.match_ref), None),
            rights_holder=first.rights_holder,
            required_materials=first.required_materials,
        ))
    return out
