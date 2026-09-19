"""采样帧数据模型。

刻意与 extract.py 分开：本模块**不引入 cv2 / imagehash / PIL**，
只用 TYPE_CHECKING 做类型标注。这样 provider、测试、找法层引用帧数据时
不会被迫拉起整个 opencv 依赖链 —— 与 evidence.py 保持同一原则。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import imagehash
    from PIL import Image


@dataclass
class SampledFrame:
    """一个采样帧。

    ⚠️ 注意 `span_start` / `span_end` 与 `t` 的区别，这是本项目一个容易踩的坑：

        t          这一帧本身的时间戳
        span_*     这一帧**代表**的时间跨度

    pHash 去重时，连续的重复帧被折叠进代表帧，时长信息就转移到了 span 里。
    OCR 只跑代表帧，但产出的证据必须用 span 而不是 t —— 否则：
      · 报告里的时间区间会缩成一个点
      · L4「免责声明只显示了 0.5 秒」这类显著性判定直接失效
        （时长信息恰恰藏在被丢掉的那些重复帧里）
    """

    frame_id: int
    t: float
    is_scene_key: bool = False
    phash: imagehash.ImageHash | None = None
    path: Path | None = None
    span_start: float = 0.0
    span_end: float = 0.0
    collapsed: int = 1
    """本帧代表了多少个原始采样帧（含自己）。用于统计去重率。"""

    _image: Any = field(default=None, repr=False, compare=False)
    """PIL Image，仅在处理期间持有。长视频下要及时置 None，否则很容易吃满内存。"""

    @property
    def span_duration(self) -> float:
        return max(0.0, self.span_end - self.span_start)
