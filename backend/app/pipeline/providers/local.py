"""本地开源 Provider —— 不需要任何云账号即可处理真实视频。

存在的理由很实际：云 ASR/OCR 要开户实名，而开户是**人**的等待，不是钱的问题
（按实测调用量，单条 30 秒广告的云成本约两毛）。在账号到位之前，
本模块让整条链路可以拿真实 mp4 跑起来，把"视频进不来"这个硬缺口解开。

    ASR  faster-whisper（CTranslate2）—— **原生字级时间戳**，不依赖 torch
    OCR  RapidOCR（ONNXRuntime）    —— 返回 bbox 与置信度，不依赖 torch

两个都不吃 GPU，模型自动下载后本地推理。

⚠️ 质量边界，必须说清楚：
   whisper 的 `base` 档中文识别很差（实测把广告口播识别成不相关的句子）。
   **它能证明机制成立，不能拿来出对外报告。** 生产用 `small` 以上，
   或换 FunASR/Paraformer（中文专优）。模型档位由 `LOCAL_ASR_MODEL` 控制。

⚠️ 置信度一律取自模型真实输出，缺失就写 None。
   替模型声称它从没声称过的确定性，在给法务看的证据里是编造数据质量。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from app.pipeline.evidence import EvidenceSource, TextEvidence, WordTiming
from app.pipeline.providers.base import (
    ASRCapabilities, ASRProvider, OCRCapabilities, OCRProvider,
    font_scale_from_bbox, to_normalized_bbox,
)

if TYPE_CHECKING:
    from app.pipeline.frames import SampledFrame

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
#  ASR · faster-whisper
# ──────────────────────────────────────────────────────────────


class LocalWhisperASR(ASRProvider):
    """faster-whisper 本地转写。

    字级时间戳是本项目的硬指标，基类会在初始化时校验能力声明；
    这里声明 True 是有实测依据的：中文逐字返回 `start` / `end` / `probability`。
    """

    name = "local-whisper"

    def __init__(self, model_size: str | None = None, device: str = "cpu",
                 compute_type: str = "int8", language: str = "zh") -> None:
        self.model_size = model_size or os.getenv("LOCAL_ASR_MODEL", "small")
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        super().__init__()   # 能力闸门在基类，放最后跑

    def capabilities(self) -> ASRCapabilities:
        return ASRCapabilities(word_timestamps=True, punctuation=True, hotwords=False)

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            logger.info("载入 whisper 模型 %s（%s/%s）",
                        self.model_size, self.device, self.compute_type)
            self._model = WhisperModel(self.model_size, device=self.device,
                                       compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: Path, hotwords: list[str] | None = None
                   ) -> list[TextEvidence]:
        model = self._load()
        # 固定温度、关闭温度回退与上文条件 —— 与 LLM 层同一条原则：
        # 同一份素材两次审核给出不同结论，法务没法用，也没法追责。
        # 实测依据：低置信度音频（字级概率 0.2–0.5）开启回退时，
        # 两次运行的分段数从 34 变成 57，证据条目对不上。
        #
        # vad_filter 不是可选项，是两个实测问题的共同解：
        #   1. 广告口播之间必然有静音/纯音乐段，whisper 在这些段上会
        #      **锁死在一个短语上反复输出，而且越重复越自信**
        #      （实测 medium 档把一段音乐认成同一个人名连出 5 段，置信度 0.91）。
        #      所以置信度不能当质量闸门，得先把无人声段切掉。
        #   2. 静音段还会让字级时间戳对齐直接崩：
        #      faster-whisper 的 find_alignment 抛 IndexError，整条视频失败。
        # initial_prompt 把输出锁到简体，这不是锦上添花，是**词库能不能匹配上**的前提。
        # 实测：whisper 对同一段普通话可能输出繁体（「本品采用國家級配方…銷量第一」），
        # 内容完全正确，但简体词库一条都匹配不上 —— 口播路召回直接归零，
        # 而且不报错、不掉置信度，是最难发现的那种失败。
        segments, _info = model.transcribe(
            str(audio_path), language=self.language, word_timestamps=True,
            temperature=0.0, condition_on_previous_text=False,
            vad_filter=True,
            initial_prompt="以下是普通话广告口播，请使用简体中文转写。")

        out: list[TextEvidence] = []
        for i, seg in enumerate(segments):
            words = [w for w in (seg.words or []) if (w.word or "").strip()]
            if not words:
                # 没有字级时间戳的段落直接丢弃：留着会让报告出现
                # 定位不到词的"伪证据"，那正是本产品要消灭的东西。
                logger.warning("段落 %.2f-%.2f 无字级时间戳，已跳过", seg.start, seg.end)
                continue

            timings, parts = [], []
            for w in words:
                txt = w.word.strip()
                parts.append(txt)
                timings.append(WordTiming(text=txt, t_start=float(w.start),
                                          t_end=float(w.end)))
            text = "".join(parts)

            # 置信度取字级概率均值 —— 是模型真给的数，不是我补的
            probs = [w.probability for w in words if w.probability is not None]
            conf = sum(probs) / len(probs) if probs else None

            out.append(TextEvidence(
                id=f"asr-{i:04d}",
                source=EvidenceSource.ASR,
                text=text,
                t_start=float(timings[0].t_start),
                t_end=float(timings[-1].t_end),
                word_timings=timings,
                confidence=conf,
                provider=self.name,
                provider_version=f"faster-whisper/{self.model_size}",
                raw_ref={"audio_path": str(audio_path)},
            ))
        return out


# ──────────────────────────────────────────────────────────────
#  OCR · RapidOCR
# ──────────────────────────────────────────────────────────────


class LocalRapidOCR(OCRProvider):
    """RapidOCR（PP-OCR 的 ONNX 版）单帧识别。

    bbox 是硬指标（L4 显著性核查完全依赖它），基类会校验；
    这里声明 True 有实测依据：返回四点多边形，本类折成轴对齐矩形。
    """

    name = "local-rapidocr"

    def __init__(self, max_calls: int) -> None:
        self._ocr = None
        super().__init__(max_calls=max_calls)

    def capabilities(self) -> OCRCapabilities:
        return OCRCapabilities(bbox=True, confidence=True)

    def _load(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
        return self._ocr

    def _recognize_impl(self, frame: SampledFrame, img_w: int, img_h: int
                        ) -> list[TextEvidence]:
        ocr = self._load()
        src = str(frame.path) if frame.path else frame._image
        if src is None:
            raise ValueError(f"帧 {frame.frame_id} 既无 path 也无内存图像，无法识别")

        result, _elapse = ocr(src)
        out: list[TextEvidence] = []
        for j, item in enumerate(result or []):
            poly, text, score = item[0], item[1], item[2]
            text = (text or "").strip()
            if not text:
                continue

            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
            bbox = to_normalized_bbox(min(xs), min(ys),
                                      max(xs) - min(xs), max(ys) - min(ys),
                                      img_w, img_h)
            out.append(TextEvidence(
                id=f"ocr-{frame.frame_id:06d}-{j:02d}",
                source=EvidenceSource.OCR,
                text=text,
                # 时间由基类用代表帧的 span 回填，这里先放帧时刻占位
                t_start=frame.t, t_end=frame.t,
                bbox=bbox,
                font_scale=font_scale_from_bbox(bbox),
                confidence=float(score) if score is not None else None,
                provider=self.name,
                provider_version="rapidocr-onnxruntime/PP-OCRv4",
                raw_ref={"frame_path": str(frame.path) if frame.path else ""},
            ))
        return out
