# -*- coding: utf-8 -*-
"""云 OCR Provider —— 复用 OpenAI 兼容视觉模型的文字识别能力。

选型说明（实施方案 v2 §6 的云 OCR 路线）：
  火山方舟的视觉理解模型（doubao-seed-2-1-pro）对中文广告画面 OCR + 归一化 bbox
  实测精度良好（大字/贴边小字误差 <1%），且与云 VLM 共用同一凭据与端点，
  不必单独开通 OCR 服务。花字/艺术字场景的召回对比待金标准集实测（§11 指标）。

与 LocalRapidOCR 的取舍：
  - 本地：零成本、无外发；速度慢、花字召回一般
  - 云：按帧计费、画面外发（审计日志留痕）；花字召回预期更好
  成本红线与本地共用（≤20 次/条，按时长折算），超限抛错行为一致。

数据外发边界：只发帧图 + OCR prompt；审计日志记录每帧 sha256。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
from typing import Callable

from app.pipeline.evidence import (
    EvidenceSource,
    TextEvidence,
)
from app.pipeline.frames import SampledFrame
from app.pipeline.providers.base import (
    OCRCapabilities,
    OCRProvider,
    font_scale_from_bbox,
    to_normalized_bbox,
)

logger = logging.getLogger(__name__)

PostFn = Callable[[str, dict, dict, float], dict]

MAX_SIDE = 1024
JPEG_QUALITY = 92

OCR_PROMPT = """识别图中全部文字（含花字、艺术字、贴边小字、半透明字幕）。
只输出 JSON 数组，每个元素：
{"text": "文字内容", "bbox": [x, y, w, h]}
bbox 为归一化坐标（左上原点，相对图宽高，w/h ≤ 1）。
无文字返回 []。只输出 JSON，不要解释。"""

_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)


class CloudOCRError(RuntimeError):
    pass


def _parse_ocr_response(content: str) -> list[dict]:
    m = _JSON_RE.search(content or "")
    if not m:
        logger.warning("云 OCR 返回中找不到 JSON 数组，按无文字处理：%.80s", content)
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("云 OCR JSON 不可解析，按无文字处理：%.80s", content)
        return []
    out = []
    for item in arr if isinstance(arr, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        bbox = item.get("bbox")
        if not text or not (isinstance(bbox, list) and len(bbox) == 4
                            and all(isinstance(v, (int, float)) for v in bbox)):
            continue
        x, y, w, h = bbox
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1
                and x + w <= 1 + 1e-6 and y + h <= 1 + 1e-6):
            continue
        out.append({"text": text, "bbox": (x, y, w, h)})
    return out


def _encode_frame(frame: SampledFrame) -> str:
    img = frame._image
    if img is None:
        if frame.path is None or not frame.path.exists():
            raise CloudOCRError(f"帧 {frame.frame_id} 无可用图像数据")
        from PIL import Image

        img = Image.open(frame.path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, MAX_SIDE / max(w, h))
    if scale < 1.0:
        img = img.resize((round(w * scale), round(h * scale)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class OpenAICompatOCR(OCRProvider):
    """OpenAI 兼容视觉模型的 OCR provider（bbox 硬指标满足，基类校验通过）。"""

    name = "openai-compat-ocr"

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str,
        max_calls: int = 20,
        timeout: float = 120.0,
        post: PostFn | None = None,
    ) -> None:
        if not api_key:
            raise CloudOCRError("云 OCR 凭据未配置（OCR_API_KEY）")
        if not endpoint.startswith("https://"):
            raise CloudOCRError("云 OCR endpoint 必须是 HTTPS")
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._post = post or self._http_post
        self.transmission_log: list[dict] = []
        super().__init__(max_calls=max_calls)

    @staticmethod
    def _http_post(url: str, body: dict, headers: dict, timeout: float) -> dict:
        import httpx

        with httpx.Client(trust_env=False, timeout=timeout,
                          follow_redirects=False) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()

    def capabilities(self) -> OCRCapabilities:
        return OCRCapabilities(bbox=True, confidence=False)

    def _recognize_impl(self, frame: SampledFrame, img_w: int, img_h: int
                        ) -> list[TextEvidence]:
        image_b64 = _encode_frame(frame)
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}],
            "temperature": 0,
            "max_tokens": 2000,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        transmission = {
            "frame_id": frame.frame_id,
            "image_sha256": hashlib.sha256(base64.b64decode(image_b64)).hexdigest(),
            "model": self.model,
        }
        self.transmission_log.append(transmission)

        raw = self._post(self.endpoint + "/chat/completions", body, headers, self.timeout)
        content = (raw.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if self.api_key and self.api_key in content:
            content = content.replace(self.api_key, "[REDACTED]")
        transmission["response_sha256"] = hashlib.sha256(content.encode()).hexdigest()

        out: list[TextEvidence] = []
        for j, item in enumerate(_parse_ocr_response(content)):
            x, y, w, h = item["bbox"]
            bbox = to_normalized_bbox(x * img_w, y * img_h, w * img_w, h * img_h,
                                      img_w, img_h)
            out.append(TextEvidence(
                id=f"ocr-{frame.frame_id:06d}-{j:02d}",
                source=EvidenceSource.OCR,
                text=item["text"],
                t_start=frame.t, t_end=frame.t,   # 基类回填 span
                bbox=bbox,
                font_scale=font_scale_from_bbox(bbox),
                confidence=None,                   # 模型未给置信度就不编
                provider=self.name,
                provider_version=self.model,
                raw_ref={"transmission": transmission},
            ))
        return out
