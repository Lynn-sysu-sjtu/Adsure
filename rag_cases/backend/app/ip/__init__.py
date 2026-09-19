"""阶段 2 · IP 形象识别。

两层顺序是刻意的（见实施方案 v2 第五节）：

    先底库（SSCD 特征 + 本地向量检索，CPU、成本为零、证据可呈堂）
    后 VLM（只兜底底库没挡住的场景关键帧，受 ≤4 次/条成本红线约束）

融合规则：
    底库命中（含双层都中）→ confirmed，进正式风险清单，带授权材料清单
    仅 VLM 命中           → suspected_pending，基类强制置位，不进正式清单

任何一层都不做侵权认定：画面里出现米奇 ≠ 侵权（可能有授权/合理使用）。
系统输出永远是「需核验的授权材料清单」。
"""

from app.ip.detector import (
    IPDetector,
    IPHit,
    HitSource,
    ReviewStatus,
    consolidate_hits,
)
from app.ip.library import IPLibrary, load_default_library, load_library
from app.ip.schema import IPLibraryEntry

__all__ = [
    "IPDetector",
    "IPHit",
    "HitSource",
    "ReviewStatus",
    "consolidate_hits",
    "IPLibrary",
    "IPLibraryEntry",
    "load_default_library",
    "load_library",
]
