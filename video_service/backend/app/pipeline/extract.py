"""视频拆解：分镜 → 抽帧 → pHash 去重 → 音轨提取。

这一层决定了两件事：
  1. **漏不漏**：抽帧策略错了，后面再准也没用
  2. **贵不贵**：OCR 按次计费，去重率直接换算成钱

抽帧策略 = 场景切换关键帧 ∪ 固定 2fps 采样
  只用场景关键帧会大面积漏检 —— 广告花字的典型形态是「同一镜头内文字不断变化」，
  场景没切但文字全换了。只用固定采样又会错过短镜头。两者取并集。

去重的关键设计：**被丢掉的帧不是消失，而是折叠进代表帧的时间跨度**。
  一条花字连续出现 3 秒 = 6 个采样帧，去重后只留 1 帧送去 OCR，
  但那 1 帧必须带着 span=(t0, t0+3.0)，否则：
    - 报告里的时间区间会缩成一个点
    - L4「免责声明只显示了 0.5 秒」这类显著性判定直接失效（时长信息就在被丢的帧里）
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import imagehash
from PIL import Image

from app.config import PipelineSettings, get_settings
from app.pipeline.evidence import VideoMeta
from app.pipeline.frames import SampledFrame

logger = logging.getLogger(__name__)


class ExtractError(RuntimeError):
    pass


@dataclass
class ExtractResult:
    meta: VideoMeta
    scenes: list[tuple[float, float]]
    frames: list[SampledFrame]
    """去重后的代表帧，按时间升序。这些才会送去 OCR。"""
    frames_sampled: int
    """去重前的采样帧总数。与 len(frames) 一起算削减率。"""
    audio_path: Path | None = None

    @property
    def dedup_ratio(self) -> float:
        if self.frames_sampled == 0:
            return 0.0
        return 1.0 - len(self.frames) / self.frames_sampled


# ──────────────────────────────────────────────────────────────
#  探测
# ──────────────────────────────────────────────────────────────


def probe_video(video_path: Path) -> VideoMeta:
    """用 ffprobe 读取视频元信息。

    不用 OpenCV 读 duration —— 它在部分容器上会返回 0 或错值。
    """
    settings = get_settings()
    cmd = [
        settings.ffprobe_bin,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
    except FileNotFoundError as exc:
        raise ExtractError(
            f"找不到 ffprobe（配置值 ={settings.ffprobe_bin}）。"
            "请安装 ffmpeg 或在 .env 里把 FFPROBE_BIN 设为绝对路径。"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise ExtractError(f"ffprobe 读取失败: {exc.stderr.strip()}") from exc

    data = json.loads(out.stdout)
    video_stream = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video_stream is None:
        raise ExtractError(f"{video_path} 里没有视频流")
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])

    # r_frame_rate 形如 "30000/1001"
    num, _, den = video_stream.get("r_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den) if den and float(den) != 0 else 0.0

    duration = float(data.get("format", {}).get("duration") or video_stream.get("duration") or 0.0)
    if duration <= 0:
        raise ExtractError(f"无法确定 {video_path} 的时长")

    return VideoMeta(
        path=str(video_path),
        duration=duration,
        fps=fps,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        has_audio=has_audio,
    )


def extract_audio(video_path: Path, out_dir: Path) -> Path | None:
    """抽出单声道 16k WAV 供 ASR 使用。无音轨返回 None。"""
    settings = get_settings()
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "audio.wav"
    cmd = [
        settings.ffmpeg_bin,
        "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(audio_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        logger.warning("音轨提取失败（可能是无声视频）: %s", exc.stderr.strip())
        return None
    return audio_path if audio_path.exists() else None


# ──────────────────────────────────────────────────────────────
#  分镜
# ──────────────────────────────────────────────────────────────


def detect_scenes(video_path: Path, threshold: float) -> list[tuple[float, float]]:
    """PySceneDetect 分镜。返回 [(start_sec, end_sec), ...]。

    失败时降级为「整条视频算一个场景」，不让分镜问题阻断主链路 ——
    固定 2fps 采样那一路仍然有效，最坏情况只是丢掉一些短镜头的首帧。
    """
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:  # pragma: no cover
        raise ExtractError("未安装 scenedetect，请先 pip install -r requirements.txt") from exc

    try:
        scene_list = detect(str(video_path), ContentDetector(threshold=threshold))
    except Exception as exc:
        logger.warning("分镜检测失败，降级为单场景: %s", exc)
        return []

    return [(s.get_seconds(), e.get_seconds()) for s, e in scene_list]


# ──────────────────────────────────────────────────────────────
#  抽帧
# ──────────────────────────────────────────────────────────────


def _target_frame_ids(meta: VideoMeta, scenes: list[tuple[float, float]], cfg: PipelineSettings) -> dict[int, bool]:
    """算出要保留哪些帧号。返回 {frame_id: is_scene_key}。

    并集语义：场景起始帧一定要（哪怕不在采样网格上），采样网格上的也要。
    """
    if meta.fps <= 0:
        raise ExtractError(f"无效帧率 fps={meta.fps}")

    targets: dict[int, bool] = {}

    # 固定采样网格
    step = meta.fps / cfg.sample_fps
    total_frames = int(meta.duration * meta.fps)
    i = 0.0
    while i < total_frames:
        targets[int(i)] = False
        i += step

    # 场景起始帧（覆盖写入，标记为关键帧）
    for start_sec, _ in scenes:
        fid = int(round(start_sec * meta.fps))
        if 0 <= fid < total_frames:
            targets[fid] = True

    return targets


def sample_frames(video_path: Path, meta: VideoMeta, scenes: list[tuple[float, float]], cfg: PipelineSettings) -> list[SampledFrame]:
    """顺序解码一遍，挑出目标帧。

    用顺序解码而不是 seek：OpenCV 在部分编码上 seek 不准，会拿到错帧，
    导致时间戳对不上 —— 而时间戳准确性是这个产品的命根子。
    30 秒视频顺序解码 ~900 帧，代价可以接受。
    """
    targets = _target_frame_ids(meta, scenes, cfg)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ExtractError(f"OpenCV 打不开 {video_path}")

    frames: list[SampledFrame] = []
    try:
        idx = 0
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            if idx in targets:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                t = idx / meta.fps
                frames.append(
                    SampledFrame(
                        frame_id=idx,
                        t=t,
                        is_scene_key=targets[idx],
                        phash=imagehash.phash(image, hash_size=cfg.phash_size),
                        span_start=t,
                        span_end=t,
                        _image=image,
                    )
                )
            idx += 1
    finally:
        cap.release()

    frames.sort(key=lambda f: f.frame_id)
    return frames


# ──────────────────────────────────────────────────────────────
#  去重
# ──────────────────────────────────────────────────────────────


def dedup_frames(frames: list[SampledFrame], cfg: PipelineSettings) -> list[SampledFrame]:
    """pHash 去重：把时间上相邻的重复帧折叠成一个代表帧。

    只跟**上一个代表帧**比，不做全局两两比较，这是刻意的：
      - 广告花字的重复是「连续出现一段时间」，重复帧必然时间相邻
      - 若某段文字消失后又重新出现，那是一次**新的出现**，应当作为独立证据保留
        （时间区间不同，报告里要分别标注）

    场景关键帧永不被折叠：镜头切了就是新画面，哪怕 pHash 相近
    （例如同一场景的两次切回），也要保留边界，否则时间区间会被错误地连成一片。
    """
    if not frames:
        return []

    kept: list[SampledFrame] = []
    for f in frames:
        if kept:
            prev = kept[-1]
            same = (
                not f.is_scene_key
                and prev.phash is not None
                and f.phash is not None
                and (prev.phash - f.phash) <= cfg.phash_hamming_threshold
            )
            if same:
                # 折叠进上一个代表帧：延长它代表的时间跨度
                prev.span_end = f.t
                prev.collapsed += 1
                f._image = None  # 及时释放，长视频下这里很容易吃满内存
                continue
        kept.append(f)

    # 补齐每个代表帧的 span_end：它应当延伸到下一个代表帧出现之前
    for i, f in enumerate(kept):
        if f.span_end <= f.span_start:
            f.span_end = kept[i + 1].t if i + 1 < len(kept) else f.t
    return kept


def save_frames(frames: list[SampledFrame], out_dir: Path, quality: int = 90) -> None:
    """把代表帧落盘，供 OCR / VLM / 报告截图使用。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in frames:
        if f._image is None:
            continue
        path = out_dir / f"frame_{f.frame_id:08d}.jpg"
        f._image.save(path, format="JPEG", quality=quality)
        f.path = path


# ──────────────────────────────────────────────────────────────
#  编排
# ──────────────────────────────────────────────────────────────


def extract(video_path: Path, work_dir: Path, cfg: PipelineSettings | None = None) -> ExtractResult:
    """完整拆解流程。这是本模块唯一对外入口。"""
    cfg = cfg or get_settings().pipeline
    video_path = Path(video_path)
    if not video_path.exists():
        raise ExtractError(f"视频不存在: {video_path}")

    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > cfg.max_video_size_mb:
        raise ExtractError(f"视频 {size_mb:.1f}MB 超过上限 {cfg.max_video_size_mb}MB")

    meta = probe_video(video_path)
    if meta.duration > cfg.max_video_duration_seconds:
        raise ExtractError(
            f"视频时长 {meta.duration:.1f}s 超过上限 {cfg.max_video_duration_seconds}s"
        )

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    scenes = detect_scenes(video_path, cfg.scene_threshold)
    sampled = sample_frames(video_path, meta, scenes, cfg)
    kept = dedup_frames(sampled, cfg)
    save_frames(kept, work_dir / "frames")

    audio_path = extract_audio(video_path, work_dir) if meta.has_audio else None

    result = ExtractResult(
        meta=meta,
        scenes=scenes,
        frames=kept,
        frames_sampled=len(sampled),
        audio_path=audio_path,
    )

    logger.info(
        "拆解完成 %s | %.1fs | %d 场景 | 采样 %d 帧 → 去重后 %d 帧（削减 %.1f%%）",
        video_path.name, meta.duration, len(scenes),
        result.frames_sampled, len(kept), result.dedup_ratio * 100,
    )

    # 只警告不抛错：削减率不达标是**成本问题**，不是正确性问题。
    # 真正的硬闸门在调 OCR 之前（max_ocr_calls_per_video），那里才该拦。
    if result.dedup_ratio < 0.70 and result.frames_sampled > 10:
        logger.warning(
            "帧去重率 %.1f%% 低于目标 70%%，OCR 成本会偏高。"
            "考虑上调 phash_hamming_threshold，或检查素材是否为持续运动画面。",
            result.dedup_ratio * 100,
        )

    return result
