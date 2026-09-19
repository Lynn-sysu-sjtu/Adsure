"""与 video-mvp 格式互转的测试。

转换器最怕的不是报错，而是**静默丢字段**——跑起来一切正常，
等到法务追问「这条证据是哪个引擎认的、原图在哪」时才发现溯源断了。
所以这里用根目录 data 下的真实 job 做**往返比对**，逐字段核对。
"""

import json
from pathlib import Path

import pytest

from app.pipeline.evidence import (
    BBox, CostRecord, EvidenceBundle, EvidenceSource,
    TextEvidence, VideoMeta, VisualEntityEvidence,
)
from app.pipeline.interop import (
    EVIDENCE_SCHEMA_V1,
    InteropError,
    evidence_from_video_mvp,
    evidences_to_video_mvp,
    frame_id_to_label,
    frame_label_to_id,
    load_job,
)

JOBS_DIR = Path(__file__).resolve().parents[2] / "data" / "video_mvp" / "jobs"
_real_jobs = sorted(p for p in JOBS_DIR.glob("*") if (p / "evidence.json").exists()) \
    if JOBS_DIR.is_dir() else []
needs_refs = pytest.mark.skipif(not _real_jobs, reason="根目录没有可用视频任务，跳过真实数据测试")


# ── 帧号 ──────────────────────────────────────────────────────


def test_frame_label_round_trip():
    for fid in (0, 2, 843, 999999):
        assert frame_label_to_id(frame_id_to_label(fid)) == fid


def test_import_export_preserves_original_frame_label_width():
    original = {
        "id": "ocr_1", "source": "ocr", "kind": "text", "text": "示例",
        "t_start": 0, "t_end": 1, "bbox": None,
        "frame_ids": ["frame_00000003"], "confidence": None,
        "provider": "test", "provider_version": "v1", "raw_ref": {},
    }
    imported = evidence_from_video_mvp(original)
    exported = evidences_to_video_mvp(_bundle([imported]))["items"][0]
    assert exported["frame_ids"] == ["frame_00000003"]


def test_frame_label_rejects_unknown_format():
    """不认识的命名必须抛错而不是猜。猜错会让证据截图指向错误的帧。"""
    with pytest.raises(InteropError, match="无法解析帧标签"):
        frame_label_to_id("img-0002.jpg")


# ── 单条转换 ──────────────────────────────────────────────────


def test_import_derives_font_scale_from_bbox():
    """他们的 schema 没有 font_scale，但归一化 bbox 的高度就是它。

    这是互转最实在的增益：他们已跑完的 job 不用重跑就能做 L4 显著性核查。
    """
    ev = evidence_from_video_mvp({
        "id": "ocr_frame_000002_000", "source": "ocr", "kind": "text",
        "text": "本品不能代替药物", "t_start": 3.0, "t_end": 4.0,
        "bbox": [0.75, 0.94, 0.20, 0.018], "frame_ids": ["frame_000002"],
        "confidence": 0.5, "provider": "Apple Vision", "provider_version": "macOS-native",
        "raw_ref": {"frame_path": "frames/frame_000002.jpg"},
    })
    assert ev.font_scale == pytest.approx(0.018)
    assert ev.frame_ids == [2]
    assert ev.provider == "Apple Vision"
    assert ev.raw_ref["frame_path"] == "frames/frame_000002.jpg"


def test_import_preserves_null_confidence():
    """来源没给置信度就如实保留 None，不能补成 1.0。

    补成 1.0 等于替对方声称了它从没声称过的确定性，
    在一份要给法务看的证据里，这是编造数据质量。
    """
    ev = evidence_from_video_mvp({
        "id": "asr_00000", "source": "asr", "kind": "text",
        "text": "首先进入我们的工作台页面", "t_start": 0.0, "t_end": 3.433,
        "bbox": None, "frame_ids": [], "confidence": None,
        "provider": "uploaded timed captions", "provider_version": "user-supplied",
        "raw_ref": {"segment_index": 0},
    })
    assert ev.confidence is None
    assert ev.bbox is None and ev.font_scale is None
    assert ev.word_timings == [], "对方是段级字幕，不能按字均分伪造字级时间戳"


def test_import_preserves_current_video_mvp_word_timings():
    ev = evidence_from_video_mvp({
        "id": "audio_000000", "source": "asr", "kind": "text",
        "text": "国家级", "t_start": 1.0, "t_end": 1.6,
        "bbox": None, "frame_ids": [], "confidence": 0.83,
        "provider": "faster-whisper", "provider_version": "medium",
        "raw_ref": {"path": "asr_raw.json", "words": [
            {"word": "国", "start": 1.0, "end": 1.2, "probability": 0.9},
            {"word": "家", "start": 1.2, "end": 1.4, "probability": 0.8},
            {"word": "级", "start": 1.4, "end": 1.6, "probability": 0.8},
        ]},
    })
    assert [word.text for word in ev.word_timings] == ["国", "家", "级"]
    assert ev.resolve_time(1, 3) == pytest.approx((1.2, 1.6))


def test_import_rejects_bad_bbox():
    with pytest.raises(InteropError, match="四元组"):
        evidence_from_video_mvp({
            "id": "x", "source": "ocr", "kind": "text", "text": "t",
            "t_start": 0, "t_end": 1, "bbox": [0.1, 0.2], "frame_ids": [],
        })


# ── 导出 ──────────────────────────────────────────────────────


def _bundle(evs):
    return EvidenceBundle(
        review_id="t", video=VideoMeta(path="t.mp4", duration=10.0),
        evidences=list(evs), cost=CostRecord(),
    )


def test_export_skips_visual_entities_and_counts_them():
    """对方 schema 没有 visual_entity 类型。

    宁可明确丢弃并计数，也不硬塞成 text —— 那会让对方的报告把
    「画面里出现米奇」渲染成一条文字证据，属于伪造证据类型。
    """
    from app.pipeline.evidence import EntityType

    bundle = _bundle([
        TextEvidence(id="o1", source=EvidenceSource.OCR, text="限时特惠",
                     t_start=1.0, t_end=2.0, bbox=BBox(x=0.1, y=0.8, w=0.3, h=0.05)),
        VisualEntityEvidence(id="ip1", source=EvidenceSource.IP_MATCH,
                             entity_name="米奇老鼠", entity_type=EntityType.CARTOON_CHARACTER,
                             t_start=12.0, t_end=14.5),
    ])
    payload = evidences_to_video_mvp(bundle)

    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "o1"
    assert payload["_export_note"]["skipped_visual_entities"] == 1, "丢了东西必须留痕"


# ── 真实数据往返 ──────────────────────────────────────────────


@needs_refs
@pytest.mark.parametrize("job_dir", _real_jobs, ids=lambda p: p.name[:8])
def test_round_trip_on_real_jobs(job_dir):
    """真实 job 往返：导入再导出，对方定义的每个字段都要逐条一致。"""
    original = json.loads((job_dir / "evidence.json").read_text(encoding="utf-8"))
    bundle = load_job(job_dir)
    exported = evidences_to_video_mvp(bundle, job_id=original["job_id"])

    assert exported["schema_version"] == EVIDENCE_SCHEMA_V1
    assert exported["job_id"] == original["job_id"]
    assert len(exported["items"]) == len(original["items"]), "条目数量不能变"

    fields = ("id", "source", "kind", "text", "t_start", "t_end",
              "frame_ids", "confidence", "provider", "provider_version", "raw_ref")
    for src, dst in zip(original["items"], exported["items"]):
        for f in fields:
            assert dst[f] == src.get(f), f"字段 {f} 在往返后变了：{src.get(f)!r} → {dst[f]!r}"
        if src["bbox"] is None:
            assert dst["bbox"] is None
        else:
            assert dst["bbox"] == pytest.approx(src["bbox"]), "bbox 数值失真"


@needs_refs
def test_load_job_builds_usable_bundle():
    bundle = load_job(_real_jobs[0])
    assert bundle.review_id
    assert bundle.video.duration > 0
    assert bundle.evidences
    # manifest 不含分辨率，如实记为 0（未知），不编一个 1920x1080 出来
    assert bundle.video.width == 0 and bundle.video.height == 0


@needs_refs
def test_imported_job_runs_through_our_pipeline():
    """把对方的产出接进本项目的链路：合并 → 违禁词 → L4。

    这条测试是互转的真正意义 —— 证明他们已跑完的 job 不用重跑，
    就能获得本项目独有的字幕合并、显著性核查等能力。
    """
    from app.config import PipelineSettings
    from app.pipeline.merge import merge_ocr
    from app.rules.mandatory import MandatoryChecker
    from app.rules.matcher import load_default_matcher

    # 挑一个 OCR 证据最多的 job，跑起来才有内容
    job = max(_real_jobs, key=lambda p: len(
        json.loads((p / "evidence.json").read_text(encoding="utf-8"))["items"]))
    bundle = load_job(job)

    before = len(bundle.texts(EvidenceSource.OCR))
    bundle.evidences = merge_ocr(list(bundle.evidences), PipelineSettings())
    after = len(bundle.texts(EvidenceSource.OCR))
    assert after < before, "逐帧 OCR 结果应当被合并成更少的花字条目"

    # 不断言具体命中数量——素材内容不受我们控制，
    # 只断言链路能跑通且产出结构正确。
    hits = load_default_matcher().match_bundle(bundle, industry=None)
    for h in hits:
        assert h.t_start >= 0 and h.t_end >= h.t_start
        assert h.entry.law_text, "每条命中都要带法条原文"

    findings = MandatoryChecker().check_bundle(bundle, industry=None)
    assert findings, "通用必备要素（广告可识别性）应当被核查"
    for f in findings:
        assert f.requirement.law_ref
