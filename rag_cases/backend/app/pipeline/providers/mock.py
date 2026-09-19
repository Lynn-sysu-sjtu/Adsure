"""Mock Provider —— 让整条链路在**拿到 API key 之前**就能端到端跑通。

这不是玩具。它的实际作用有三个：

1. **解阻塞**：找法层、用法层、报告、前端都能立刻开发联调，
   不用干等云账号开通。三个人可以并行推进。
2. **确定性测试**：真云 API 每次返回都可能有微小差异，
   无法用来断言"时间戳换算是否正确"这类逻辑。Mock 可以。
3. **成本为零的回归**：CI 里跑全链路不烧钱。

⚠️ Mock 的 capabilities 刻意声明为**满足硬指标**（有字级时间戳、有 bbox），
   否则基类的能力闸门会把它拦下来。这是符合语义的：
   Mock 扮演的正是一个合格 provider。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from app.pipeline.evidence import (
    BBox,
    EvidenceSource,
    TextEvidence,
    VisualEntityEvidence,
    WordTiming,
)
from app.pipeline.providers.base import (
    ASRCapabilities,
    ASRProvider,
    OCRCapabilities,
    OCRProvider,
    VLMProvider,
)

if TYPE_CHECKING:
    from app.pipeline.frames import SampledFrame


# ──────────────────────────────────────────────────────────────
#  ASR
# ──────────────────────────────────────────────────────────────


@dataclass
class ScriptedUtterance:
    """一句预设口播。char_duration 用于把整句均匀铺成字级时间戳。"""

    text: str
    t_start: float
    char_duration: float = 0.18


class MockASRProvider(ASRProvider):
    name = "mock"

    def __init__(self, utterances: list[ScriptedUtterance] | None = None) -> None:
        self.utterances = utterances or []
        super().__init__()

    def capabilities(self) -> ASRCapabilities:
        return ASRCapabilities(word_timestamps=True, punctuation=True, hotwords=True)

    def transcribe(self, audio_path: Path, hotwords: list[str] | None = None) -> list[TextEvidence]:
        out: list[TextEvidence] = []
        for i, utt in enumerate(self.utterances):
            # 逐字铺时间戳，模拟真实 ASR 的 word-level 输出。
            # 中文按字切分是合理近似 —— Paraformer 等中文 ASR 本身就给字级时间戳。
            timings: list[WordTiming] = []
            t = utt.t_start
            for ch in utt.text:
                timings.append(WordTiming(text=ch, t_start=t, t_end=t + utt.char_duration))
                t += utt.char_duration

            out.append(
                TextEvidence(
                    id=f"asr_{i:04d}",
                    source=EvidenceSource.ASR,
                    text=utt.text,
                    t_start=utt.t_start,
                    t_end=t,
                    word_timings=timings,
                    confidence=0.95,
                )
            )
        return out

    @classmethod
    def from_fixture(cls, path: Path) -> MockASRProvider:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([ScriptedUtterance(**item) for item in data.get("asr", [])])


# ──────────────────────────────────────────────────────────────
#  OCR
# ──────────────────────────────────────────────────────────────


@dataclass
class ScriptedTextBlock:
    """一块预设画面文字。bbox 用归一化坐标，与真实 provider 归一化后的输出一致。"""

    text: str
    bbox: tuple[float, float, float, float] = (0.1, 0.8, 0.5, 0.06)
    frame_index: int = 0
    """指向 frames 列表的下标，决定这块文字挂在哪一帧上。"""


class MockOCRProvider(OCRProvider):
    name = "mock"

    def __init__(self, blocks: list[ScriptedTextBlock] | None = None, max_calls: int = 20) -> None:
        self.blocks = blocks or []
        self._counter = 0
        super().__init__(max_calls=max_calls)

    def capabilities(self) -> OCRCapabilities:
        return OCRCapabilities(bbox=True, confidence=True)

    def _recognize_impl(self, frame: SampledFrame, img_w: int, img_h: int) -> list[TextEvidence]:
        # 基类按顺序逐帧调用，用调用序号对应 frame_index
        idx = self._counter
        self._counter += 1

        out: list[TextEvidence] = []
        for block in (b for b in self.blocks if b.frame_index == idx):
            x, y, w, h = block.bbox
            bbox = BBox(x=x, y=y, w=w, h=h)
            out.append(
                TextEvidence(
                    id=f"ocr_{frame.frame_id:08d}_{len(out)}",
                    source=EvidenceSource.OCR,
                    text=block.text,
                    # t_start/t_end 会被基类用 frame.span 覆盖，这里给占位值
                    t_start=frame.t,
                    t_end=frame.t,
                    bbox=bbox,
                    font_scale=bbox.h,
                    confidence=0.92,
                )
            )
        return out

    @classmethod
    def from_fixture(cls, path: Path, max_calls: int = 20) -> MockOCRProvider:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        blocks = [
            ScriptedTextBlock(
                text=item["text"],
                bbox=tuple(item.get("bbox", (0.1, 0.8, 0.5, 0.06))),
                frame_index=item.get("frame_index", 0),
            )
            for item in data.get("ocr", [])
        ]
        return cls(blocks, max_calls=max_calls)


# ──────────────────────────────────────────────────────────────
#  VLM
# ──────────────────────────────────────────────────────────────


@dataclass
class ScriptedEntity:
    entity_name: str
    entity_type: str
    rights_holder: str | None = None
    bbox: tuple[float, float, float, float] = (0.1, 0.1, 0.2, 0.3)
    confidence: float = 0.8
    frame_index: int = 0


class MockVLMProvider(VLMProvider):
    name = "mock"

    def __init__(self, entities: list[ScriptedEntity] | None = None, max_calls: int = 4) -> None:
        self.entities = entities or []
        self._batch_no = 0
        super().__init__(max_calls=max_calls)

    def _scan_impl(self, frames: list[SampledFrame]) -> list[VisualEntityEvidence]:
        from app.pipeline.evidence import EntityType

        frame_by_index = {i: f for i, f in enumerate(frames)}
        out: list[VisualEntityEvidence] = []
        for ent in self.entities:
            frame = frame_by_index.get(ent.frame_index)
            if frame is None:
                continue
            x, y, w, h = ent.bbox
            out.append(
                VisualEntityEvidence(
                    id=f"vlm_{frame.frame_id:08d}_{len(out)}",
                    source=EvidenceSource.VLM,
                    entity_name=ent.entity_name,
                    entity_type=EntityType(ent.entity_type),
                    rights_holder=ent.rights_holder,
                    t_start=frame.span_start,
                    t_end=max(frame.span_end, frame.span_start),
                    bbox=BBox(x=x, y=y, w=w, h=h),
                    confidence=ent.confidence,
                    frame_ids=[frame.frame_id],
                    # needs_human_review 由基类 scan() 强制置 True，这里不设
                )
            )
        self._batch_no += 1
        return out
