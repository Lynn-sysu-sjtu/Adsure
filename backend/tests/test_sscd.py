"""SSCD embedder 测试：维度/归一化/裁剪恢复/协议兼容/小目标结论锁定。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.ip.sscd import SSCDEmbedder
from app.pipeline.frames import SampledFrame
from app.pipeline.providers.base import VLMProvider  # noqa: F401 协议存在性
from app.ip.vectors import FrameEmbedder, PurePythonVectorIndex, VectorMeta

WEIGHTS = (Path(__file__).resolve().parents[2] / "data" / "ip_models"
           / "sscd_disc_mixup.torchscript.pt")

pytestmark = pytest.mark.skipif(
    not WEIGHTS.exists(), reason="SSCD 权重未下载（data/ip_models/）")


@pytest.fixture(scope="module")
def embedder():
    return SSCDEmbedder(WEIGHTS)


def _mickey_image() -> Image.Image:
    img = Image.new("RGB", (640, 480), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([250, 150, 390, 290], fill=(40, 40, 40))
    d.ellipse([230, 120, 290, 180], fill=(40, 40, 40))
    d.ellipse([350, 120, 410, 180], fill=(40, 40, 40))
    d.ellipse([290, 210, 350, 260], fill=(230, 230, 230))
    return img


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_embed_dim_and_l2_normalized(embedder):
    v = embedder.embed_image(_mickey_image())
    assert len(v) == 512
    assert abs(sum(x * x for x in v) - 1.0) < 1e-3


def test_crop_recovers_small_target_similarity(embedder):
    """核心结论锁定：小目标整帧比对失效，bbox 裁剪后恢复。

    这是本模块存在的理由——广告里 IP 通常只占画面一小块。
    """
    base = _mickey_image()
    e_base = embedder.embed_image(base)

    # 目标贴进大画面，只占 ~15%
    ad = Image.new("RGB", (1280, 720), (240, 230, 220))
    small = base.resize((192, 144))
    ad.paste(small, (1000, 520))
    e_ad_full = embedder.embed_image(ad)

    # bbox 裁剪（模拟 VLM 输出的目标位置）
    e_ad_crop = embedder.embed_crop(ad, (1000 / 1280, 520 / 720,
                                         192 / 1280, 144 / 720))

    sim_full = _cos(e_base, e_ad_full)
    sim_crop = _cos(e_base, e_ad_crop)
    assert sim_full < 0.3, f"小目标整帧比对应当失效，实际 {sim_full:.3f}"
    assert sim_crop > 0.7, f"bbox 裁剪后应恢复相似度，实际 {sim_crop:.3f}"
    assert sim_crop > sim_full + 0.4


def test_different_images_low_similarity(embedder):
    e1 = embedder.embed_image(_mickey_image())
    other = Image.new("RGB", (640, 480), (30, 90, 160))
    e2 = embedder.embed_image(other)
    assert _cos(e1, e2) < 0.3


def test_implements_frame_embedder_protocol(embedder):
    assert isinstance(embedder, FrameEmbedder)
    assert embedder.dim == 512


def test_embed_frames_with_sampled_frames(embedder, tmp_path):
    img = _mickey_image()
    p = tmp_path / "frame_000001.jpg"
    img.save(p, format="JPEG")
    f = SampledFrame(frame_id=1, t=0.0, span_start=0.0, span_end=1.0,
                     path=p, _image=None)
    vecs = embedder.embed_frames([f])
    assert len(vecs) == 1 and len(vecs[0]) == 512


def test_index_roundtrip_with_sscd_vectors(embedder):
    """SSCD 向量进 PurePythonVectorIndex 检索：同图命中、异图不命中。"""
    idx = PurePythonVectorIndex(dim=512)
    e_mickey = embedder.embed_image(_mickey_image())
    other = Image.new("RGB", (640, 480), (30, 90, 160))
    idx.add(e_mickey, VectorMeta("disney_mickey", "mickey_001.jpg"))
    idx.add(embedder.embed_image(other), VectorMeta("other", "other_001.jpg"))

    hits = idx.search(embedder.embed_image(_mickey_image()), k=1)
    assert hits[0].ip_id == "disney_mickey"
    assert hits[0].score > 0.95

    # 裁剪变体也应命中同一 IP（bbox 场景）
    ad = Image.new("RGB", (1280, 720), (240, 230, 220))
    small = _mickey_image().resize((192, 144))
    ad.paste(small, (1000, 520))
    q = embedder.embed_crop(ad, (1000 / 1280, 520 / 720, 192 / 1280, 144 / 720))
    hits2 = idx.search(q, k=1)
    assert hits2[0].ip_id == "disney_mickey"
    assert hits2[0].score > 0.7


def test_missing_weights_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="SSCD 权重不存在"):
        SSCDEmbedder(tmp_path / "nope.pt")
