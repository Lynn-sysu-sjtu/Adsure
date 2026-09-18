# -*- coding: utf-8 -*-
"""SSCD copy-detection embedder（实施方案 v2 §6 精排选型）。

模型：facebookresearch/sscd-copy-detection 的 TorchScript 版
（sscd_disc_mixup，MIT 许可，ResNet50 + GeM pooling + L2 norm，512 维）。
TorchScript 免 SSCD 代码依赖，任何 pytorch 项目直接加载。

⚠️ 实测关键结论（2026-09-19 spike，写进设计防止后人踩坑）：
  SSCD 对**小目标不敏感**——目标占画面 <50% 时相似度骤降（15% 占比 → 0.08）。
  广告里 IP 形象通常只占画面一小块，**必须先用 bbox 裁剪目标区域再算 embedding**。
  bbox 来源：VLM 巡检输出（cloud_vlm.py）或后续目标检测模型。
  裁剪后相似度可恢复到 0.86+（spike 实测）。

预处理与官方 inference.py 一致：resize 288 → center crop 256 → ImageNet normalize。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import torch
import torchvision.transforms as T
from PIL import Image

from app.pipeline.frames import SampledFrame

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = (Path(__file__).resolve().parents[3] / "data" / "ip_models"
                   / "sscd_disc_mixup.torchscript.pt")
TRANSFORM = T.Compose([
    T.Resize(288, interpolation=T.InterpolationMode.BICUBIC),
    T.CenterCrop(256),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


class SSCDEmbedder:
    """帧（或 bbox 裁剪区域）→ 512 维 L2 归一化向量。

    实现 app.ip.vectors.FrameEmbedder 协议；线程安全（torch 推理加锁）。
    """

    name = "sscd-disc-mixup"
    dim = 512

    def __init__(self, weights_path: Path | str = DEFAULT_WEIGHTS,
                 device: str = "cpu") -> None:
        path = Path(weights_path)
        if not path.exists():
            raise FileNotFoundError(
                f"SSCD 权重不存在：{path}\n"
                "下载：https://dl.fbaipublicfiles.com/sscd-copy-detection/"
                "sscd_disc_mixup.torchscript.pt（MIT 许可）")
        self._lock = threading.Lock()
        self._model = torch.jit.load(str(path), map_location=device)
        self._model.eval()
        logger.info("SSCD 模型已加载：%s（%s）", path.name, device)

    def _prep(self, img: Image.Image) -> torch.Tensor:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        return TRANSFORM(img).unsqueeze(0)

    def embed_image(self, img: Image.Image) -> list[float]:
        with self._lock, torch.no_grad():
            vec = self._model(self._prep(img))[0]
        return [round(float(x), 6) for x in vec]

    def embed_crop(self, img: Image.Image, bbox: tuple[float, float, float, float]
                   ) -> list[float]:
        """按归一化 bbox 裁剪后计算 embedding。

        这是广告场景的**默认用法**：先裁目标再算，小目标相似度才有效。
        """
        W, H = img.size
        x, y, w, h = bbox
        # 归一化 → 像素，外扩 10% 容忍 bbox 边缘误差
        px, py = max(0, int((x - w * 0.1) * W)), max(0, int((y - h * 0.1) * H))
        pw, ph = min(W - px, int(w * 1.2 * W)), min(H - py, int(h * 1.2 * H))
        if pw <= 0 or ph <= 0:
            raise ValueError(f"bbox 裁剪区域无效：{bbox}")
        return self.embed_image(img.crop((px, py, px + pw, py + ph)))

    # ── FrameEmbedder 协议 ────────────────────────────────────

    def embed_frames(self, frames: list[SampledFrame]) -> list[list[float]]:
        """整帧 embedding。⚠️ 广告场景小目标多，优先用 embed_crop。"""
        out = []
        for f in frames:
            img = f._image
            if img is None:
                if f.path is None or not f.path.exists():
                    raise ValueError(f"帧 {f.frame_id} 无可用图像")
                img = Image.open(f.path)
            out.append(self.embed_image(img))
        return out


def load_default_embedder() -> SSCDEmbedder:
    return SSCDEmbedder()
