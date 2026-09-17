# -*- coding: utf-8 -*-
"""SSCD 特征 + 向量检索（实施方案 v2 第五节）。

本期的边界：
  - 真正的 SSCD copy-detection 模型（facebookresearch/sscd-copy-detection, MIT）
    需要 torch + 权重；「参考图 → SSCD 特征建索引」的构建脚本是下一个任务。
  - 这里先把「帧 → 向量 → ip_id/ref_name」这条契约用纯 Python 余弦检索钉死，
    等模型到位后只换 Embedder 实现（Provider 抽象同款思路）。

为什么不用 CLIP 做精排（方案 §6）：CLIP 是语义 embedding，判「同一类东西」，
不判「同一个形象被裁剪/加水印/画中画变形后贴进广告」。粗召回可考虑 CLIP，
精排必须 SSCD。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.pipeline.frames import SampledFrame


@dataclass(frozen=True)
class VectorMeta:
    ip_id: str
    ref_name: str


@dataclass(frozen=True)
class SearchHit:
    score: float
    ip_id: str
    ref_name: str


@runtime_checkable
class FrameEmbedder(Protocol):
    """单帧 → L2 归一化向量。真实实现（SSCD）与脚本替身都遵守它。"""

    name: str
    dim: int

    def embed_frames(self, frames: list[SampledFrame]) -> list[list[float]]: ...


class PurePythonVectorIndex:
    """库只有数千张图（方案 §6），纯 Python 点积足够测试与首期联调。

    faiss/torch 到位后新增一个同 Protocol 的 FaissIndex 即可，业务代码不动。
    向量统一 L2 归一化，内积即余弦相似度。
    """

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._vectors: list[list[float]] = []
        self._metas: list[VectorMeta] = []

    def __len__(self) -> int:
        return len(self._metas)

    def add(self, vector: list[float], meta: VectorMeta) -> None:
        if len(vector) != self.dim:
            raise ValueError(f"向量维度 {len(vector)} ≠ 索引维度 {self.dim}")
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            raise ValueError("零向量不能入库")
        self._vectors.append([x / norm for x in vector])
        self._metas.append(meta)

    def search(self, vector: list[float], k: int = 1) -> list[SearchHit]:
        if not self._vectors:
            return []
        if len(vector) != self.dim:
            raise ValueError(f"查询维度 {len(vector)} ≠ 索引维度 {self.dim}")
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            return []
        q = [x / norm for x in vector]
        scored = []
        for i, v in enumerate(self._vectors):
            score = max(-1.0, min(1.0, sum(a * b for a, b in zip(q, v))))
            scored.append((score, i))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchHit(score=round(s, 6), ip_id=self._metas[i].ip_id,
                      ref_name=self._metas[i].ref_name)
            for s, i in scored[:k]
        ]

    def ip_counts(self) -> dict[str, int]:
        """每个 ip_id 的参考图数量，供建库脚本核对覆盖是否充分。"""
        counts: dict[str, int] = {}
        for m in self._metas:
            counts[m.ip_id] = counts.get(m.ip_id, 0) + 1
        return counts
