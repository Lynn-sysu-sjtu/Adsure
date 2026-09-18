# -*- coding: utf-8 -*-
"""OpenAI 兼容云 VLM Provider（火山方舟 Ark / 任何 /chat/completions 端点）。

IP 巡检兜底层（实施方案 v2 §5：底库优先，VLM 只扫底库没挡住的帧）。
协议与旧 MVP（src/video_mvp/semantics.py）实测过的火山方舟接入一致：
OpenAI 兼容 /chat/completions + base64 图片 + temperature=0。

数据外发边界（继承旧 MVP 的强制约定）：
  - 只发帧图（JPEG base64）与 IP 巡检 prompt，不发完整视频/口播音频/材料；
  - 每批帧的 sha256 记入 raw_ref，可审计「到底发过什么」；
  - 凭据只从构造参数/env 读，日志与异常不落 key（响应内容里出现 key 一律 REDACTED）。

硬约束：temperature=0 —— 法务结果必须可复现，同素材两次审核结论不能漂。
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from pathlib import Path
from typing import Callable

from app.ip.prompts import SYSTEM_PROMPT, build_scan_prompt, parse_vlm_response
from app.pipeline.evidence import (
    BBox,
    EntityType,
    EvidenceSource,
    VisualEntityEvidence,
)
from app.pipeline.frames import SampledFrame
from app.pipeline.providers.base import VLMProvider

logger = logging.getLogger(__name__)

PostFn = Callable[[str, dict, dict, float], dict]

# 单帧最长边压到 1024px（旧 MVP 实测值）：省 token 且不影响 IP 识别
MAX_SIDE = 1024
JPEG_QUALITY = 90


class CloudVLMError(RuntimeError):
    pass


def _encode_frame(frame: SampledFrame) -> str:
    """帧 → JPEG base64。优先用处理期持有的 PIL Image，落盘帧则从盘读。"""
    img = frame._image
    if img is None:
        if frame.path is None or not frame.path.exists():
            raise CloudVLMError(f"帧 {frame.frame_id} 无可用图像数据")
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


class OpenAICompatVLM(VLMProvider):
    """OpenAI 兼容 /chat/completions 的 IP 巡检 provider。

    post(url, body, headers, timeout) 可注入替身做离线测试；
    默认实现用 httpx（trust_env=False，不读代理环境，行为与旧 MVP 一致）。
    """

    name = "openai-compat-vlm"

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model: str,
        max_calls: int = 4,
        batch_size: int = 4,
        timeout: float = 180.0,
        post: PostFn | None = None,
    ) -> None:
        super().__init__(max_calls=max_calls)
        if not api_key:
            raise CloudVLMError("云 VLM 凭据未配置（VLM_API_KEY）")
        if not endpoint.startswith("https://"):
            raise CloudVLMError("云 VLM endpoint 必须是 HTTPS")
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.batch_size = batch_size
        self.timeout = timeout
        self._post = post or self._http_post
        self.transmission_log: list[dict] = []

    @staticmethod
    def _http_post(url: str, body: dict, headers: dict, timeout: float) -> dict:
        import httpx

        with httpx.Client(trust_env=False, timeout=timeout,
                          follow_redirects=False) as client:
            response = client.post(url, json=body, headers=headers)
            response.raise_for_status()
            return response.json()

    def _scan_impl(self, frames: list[SampledFrame]) -> list[VisualEntityEvidence]:
        images = [_encode_frame(f) for f in frames]
        prompt = build_scan_prompt(len(frames))

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content":
                    [{"type": "text", "text": prompt}]
                    + [{"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{i}"}}
                       for i in images]},
            ],
            "temperature": 0,
            "max_tokens": 2400,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        transmission = {
            "frame_ids": [f.frame_id for f in frames],
            "image_sha256": [__import__("hashlib").sha256(
                base64.b64decode(i)).hexdigest() for i in images],
            "prompt_sha256": __import__("hashlib").sha256(
                prompt.encode()).hexdigest(),
            "model": self.model,
        }
        self.transmission_log.append(transmission)

        raw = self._post(self.endpoint + "/chat/completions", body, headers, self.timeout)
        content = (raw.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if self.api_key and self.api_key in content:
            content = content.replace(self.api_key, "[REDACTED]")
        transmission["response_sha256"] = __import__("hashlib").sha256(
            content.encode()).hexdigest()

        entities, uncertainty = parse_vlm_response(content)
        out: list[VisualEntityEvidence] = []
        for i, ent in enumerate(entities):
            fi = ent["frame_index"]
            if fi >= len(frames):
                continue
            frame = frames[fi]
            bbox = None
            if ent.get("bbox"):
                x, y, w, h = ent["bbox"]
                try:
                    bbox = BBox(x=x, y=y, w=w, h=h)
                except Exception:  # noqa: BLE001 — 坏 bbox 降级为 None，不整条丢
                    bbox = None
            try:
                etype = EntityType(ent["entity_type"])
            except ValueError:
                etype = EntityType.OTHER
            out.append(VisualEntityEvidence(
                id=f"vlm_{frame.frame_id:08d}_{i}",
                source=EvidenceSource.VLM,
                entity_name=ent["name_cn"],
                entity_type=etype,
                ip_id=ent.get("ip_id"),
                t_start=frame.span_start,
                t_end=max(frame.span_end, frame.span_start),
                bbox=bbox,
                confidence=ent.get("confidence") or None,
                frame_ids=[frame.frame_id],
                provider=f"{self.name}/{self.model}",
                raw_ref={"transmission": transmission, "uncertainty": uncertainty},
                # needs_human_review 由基类 scan() 强制置 True
            ))
        return out
