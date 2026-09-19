"""与团队既有 video-mvp 格式互转。

背景：团队已有一套本机视频审核 MVP（macOS / Apple Vision），产出格式是
`video-mvp-evidence/v1`。它和本项目的 EvidenceUnit 是独立设计的，
但结构几乎重合——两边都收敛到了「带时间戳与画面位置的证据条目」。

有了这个转换器，两套系统不必二选一：

    他们的产出 → 本项目      能立刻跑本项目的字幕合并、违禁词粗筛、L4 显著性核查
    本项目产出 → 他们的格式   能被既有的报告与人工复核流程直接消费

字段对应（差异都在这里，别的都是同名同义）：

    video-mvp                    本项目
    ─────────────────────────────────────────────────────────────
    bbox: [x, y, w, h] | null    BBox 对象 | None
    frame_ids: ["frame_000002"]  [2]                （见下）
    confidence: float | null     float | None       （null 如实保留）
    —                            font_scale         （导入时由 bbox 高度推导）
    raw_ref.words                word_timings       （有则原样保留；没有则保持段级）
    —                            kind=visual_entity （他们的 v1 不支持，导出时跳过）

⚠️ frame_ids 的字符串标签与整数帧号之间要能无损往返。
   当前根目录 data/video_mvp/jobs 的任务沿用
   `frame_%06d`；若将来遇到别的命名，`frame_label_to_id` 会抛错而不是猜，
   因为猜错会让报告里的证据截图指向错误的帧。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.pipeline.evidence import (
    BBox,
    CostRecord,
    Evidence,
    EvidenceBundle,
    EvidenceSource,
    TextEvidence,
    VideoMeta,
    VisualEntityEvidence,
    WordTiming,
)

logger = logging.getLogger(__name__)

EVIDENCE_SCHEMA_V1 = "video-mvp-evidence/v1"
_FRAME_LABEL = re.compile(r"^frame_(\d+)$")
FRAME_LABEL_FMT = "frame_{:06d}"


class InteropError(ValueError):
    pass


# ──────────────────────────────────────────────────────────────
#  帧号
# ──────────────────────────────────────────────────────────────


def frame_label_to_id(label: str | int) -> int:
    """"frame_000002" → 2。无法识别时抛错，不做猜测。"""
    if isinstance(label, int):
        return label
    m = _FRAME_LABEL.match(str(label))
    if not m:
        raise InteropError(
            f"无法解析帧标签 {label!r}（期望 frame_000002 这种形式）。\n"
            "这里不做兜底猜测：猜错会让报告里的证据截图指向错误的帧，"
            "而错误的证据比没有证据更糟。"
        )
    return int(m.group(1))


def frame_id_to_label(frame_id: int) -> str:
    return FRAME_LABEL_FMT.format(frame_id)


# ──────────────────────────────────────────────────────────────
#  导入：video-mvp → 本项目
# ──────────────────────────────────────────────────────────────


def evidence_from_video_mvp(item: dict) -> Evidence:
    """单条证据的转换。"""
    kind = item.get("kind", "text")
    if kind != "text":
        raise InteropError(f"video-mvp v1 只定义了 kind=text，收到 {kind!r}")

    raw_bbox = item.get("bbox")
    bbox = None
    if raw_bbox is not None:
        if len(raw_bbox) != 4:
            raise InteropError(f"bbox 应为 [x, y, w, h] 四元组，收到 {raw_bbox!r}")
        x, y, w, h = raw_bbox
        bbox = BBox(x=x, y=y, w=w, h=h)

    source = EvidenceSource(item["source"])

    raw_ref = item.get("raw_ref") or {}
    timings: list[WordTiming] = []
    for raw_word in raw_ref.get("words") or []:
        if not isinstance(raw_word, dict):
            continue
        text = str(raw_word.get("word") or raw_word.get("text") or "")
        start = raw_word.get("start")
        end = raw_word.get("end")
        if not text or start is None or end is None:
            continue
        timings.append(WordTiming(text=text, t_start=float(start), t_end=float(end)))

    raw_frame_labels = [str(label) for label in item.get("frame_ids") or []]

    return TextEvidence(
        id=item["id"],
        source=source,
        text=item.get("text", ""),
        t_start=float(item["t_start"]),
        t_end=float(item["t_end"]),
        bbox=bbox,
        # 他们的 schema 没有 font_scale，但归一化 bbox 的高度就是它。
        # 顺手推导出来，导入后即可直接跑 L4 显著性核查——
        # 这是互转最实在的一处增益：他们已跑完的 job 不用重跑就能多一项能力。
        font_scale=bbox.h if bbox is not None else None,
        confidence=item.get("confidence"),
        frame_ids=[frame_label_to_id(f) for f in raw_frame_labels],
        frame_labels=raw_frame_labels,
        provider=item.get("provider"),
        provider_version=item.get("provider_version"),
        raw_ref=raw_ref,
        # Current video-mvp ASR stores provider word timings in raw_ref.  Older
        # uploaded-caption jobs do not; those correctly remain segment-level.
        # Never manufacture per-character timestamps by interpolation.
        word_timings=timings,
    )


def evidences_from_video_mvp(payload: dict) -> list[Evidence]:
    schema = payload.get("schema_version")
    if schema != EVIDENCE_SCHEMA_V1:
        logger.warning("证据 schema 为 %r，本转换器针对 %r 编写，字段可能已变动。",
                       schema, EVIDENCE_SCHEMA_V1)
    return [evidence_from_video_mvp(it) for it in payload.get("items", [])]


def load_job(job_dir: Path | str) -> EvidenceBundle:
    """读取一个 video-mvp job 目录，组装成本项目的证据包。

    读 evidence.json 取证据，读 manifest.json / job.json 取视频元信息。
    ⚠️ manifest 不含分辨率与帧率，VideoMeta 的 width/height/fps 会是 0（表示未知）。
       bbox 已归一化，这不影响任何分析，只影响换算回像素坐标。
    """
    job_dir = Path(job_dir)
    ev_path = job_dir / "evidence.json"
    if not ev_path.exists():
        raise InteropError(f"{job_dir} 下没有 evidence.json")

    evidences = evidences_from_video_mvp(json.loads(ev_path.read_text(encoding="utf-8")))

    manifest, job = {}, {}
    if (p := job_dir / "manifest.json").exists():
        manifest = json.loads(p.read_text(encoding="utf-8"))
    if (p := job_dir / "job.json").exists():
        job = json.loads(p.read_text(encoding="utf-8"))

    src = manifest.get("source") or {}
    extraction = manifest.get("extraction") or {}
    frame_count = int(extraction.get("frame_count") or 0)

    meta = VideoMeta(
        path=job.get("original_file_name") or src.get("file_name") or "unknown.mp4",
        duration=float(src.get("duration_seconds") or 0.0),
        has_audio=bool(job.get("transcript_text") or
                       any(e.source == EvidenceSource.ASR for e in evidences)),
    )

    bundle = EvidenceBundle(
        review_id=job.get("job_id") or manifest.get("job_id") or job_dir.name,
        video=meta,
        evidences=evidences,
        cost=CostRecord(
            ocr_calls=frame_count,
            frames_sampled=frame_count,
            # 他们没有去重环节，抽多少帧就 OCR 多少帧
            frames_after_dedup=frame_count,
        ),
    )
    logger.info(
        "导入 job %s：%d 条证据（OCR %d / ASR %d），时长 %.1fs",
        bundle.review_id, len(evidences),
        len(bundle.texts(EvidenceSource.OCR)), len(bundle.texts(EvidenceSource.ASR)),
        meta.duration,
    )
    return bundle


# ──────────────────────────────────────────────────────────────
#  导出：本项目 → video-mvp
# ──────────────────────────────────────────────────────────────


def evidence_to_video_mvp(ev: Evidence) -> dict:
    bbox = None
    if isinstance(ev, TextEvidence) and ev.bbox is not None:
        bbox = [ev.bbox.x, ev.bbox.y, ev.bbox.w, ev.bbox.h]

    return {
        "id": ev.id,
        "source": ev.source.value,
        "kind": "text",
        "text": ev.text if isinstance(ev, TextEvidence) else "",
        "t_start": ev.t_start,
        "t_end": ev.t_end,
        "bbox": bbox,
        "frame_ids": (
            list(ev.frame_labels)
            if ev.frame_labels and len(ev.frame_labels) == len(ev.frame_ids)
            else [frame_id_to_label(f) for f in ev.frame_ids]
        ),
        "confidence": ev.confidence,
        "provider": ev.provider,
        "provider_version": ev.provider_version,
        "raw_ref": ev.raw_ref or {},
    }


def evidences_to_video_mvp(bundle: EvidenceBundle, job_id: str | None = None) -> dict:
    """导出为 video-mvp-evidence/v1。

    ⚠️ 视觉实体证据（IP 命中）会被**跳过并计数**，因为对方 schema v1 没有
       kind=visual_entity。宁可明确丢弃并告知，也不硬塞成 text —— 那会让
       对方的报告把「画面里出现米奇」渲染成一条文字证据，属于伪造证据类型。
    """
    items, skipped = [], 0
    for ev in bundle.evidences:
        if isinstance(ev, VisualEntityEvidence):
            skipped += 1
            continue
        items.append(evidence_to_video_mvp(ev))

    if skipped:
        logger.warning(
            "导出时跳过 %d 条视觉实体证据（IP 命中）：video-mvp-evidence/v1 无对应类型。"
            "这部分风险不会出现在对方的报告里，需另行传递。", skipped
        )

    return {
        "schema_version": EVIDENCE_SCHEMA_V1,
        "job_id": job_id or bundle.review_id,
        "items": items,
        # 非 v1 标准字段，放在下划线前缀里，对方解析时会忽略，
        # 但人翻这份文件时能立刻看到有东西被丢掉了。
        "_export_note": {
            "exported_by": "adsure-video",
            "skipped_visual_entities": skipped,
        } if skipped else None,
    }


def save_as_video_mvp(bundle: EvidenceBundle, path: Path | str, job_id: str | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = evidences_to_video_mvp(bundle, job_id)
    if payload.get("_export_note") is None:
        payload.pop("_export_note", None)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
