from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from concurrent.futures import ThreadPoolExecutor

from .models import EvidenceUnit
from .rules import analyze_rules
from .transcript import transcript_evidence
from .vision import VisionExtractionError, extract_video_frames
from .asr import transcribe_video
from .textmatch import catalog as pattern_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )


def _normalise_bbox(raw: Iterable[float] | None) -> list[float] | None:
    if raw is None:
        return None
    values = [max(0.0, min(1.0, float(value))) for value in raw]
    return values if len(values) == 4 else None


def _ocr_evidence(native_result: dict[str, Any], duration: float, interval: float) -> list[EvidenceUnit]:
    evidence: list[EvidenceUnit] = []
    for frame in native_result.get("frames", []):
        timestamp = float(frame.get("timestamp", 0.0))
        frame_id = str(frame.get("frameId", ""))
        image_path = Path(str(frame.get("imagePath", "")))
        raw_ref = f"frames/{image_path.name}" if image_path.name else None
        for index, observation in enumerate(frame.get("ocr", [])):
            text = str(observation.get("text", "")).strip()
            if not text:
                continue
            evidence.append(
                EvidenceUnit(
                    id=f"ocr_{frame_id}_{index:03d}",
                    source="ocr",
                    kind="text",
                    text=text,
                    t_start=timestamp,
                    t_end=timestamp,
                    confidence=float(observation.get("confidence", 0.0)),
                    bbox=_normalise_bbox(observation.get("bbox")),
                    frame_ids=[frame_id],
                    provider="Apple Vision/VNRecognizeTextRequest",
                    provider_version="macOS-native",
                    raw_ref={"frame_path": raw_ref, "time_basis": "sampled_instant",
                             "frame_sha256": _sha256(image_path) if image_path.is_file() else None},
                )
            )
    return evidence


def _retrieve_cases(
    evidence: list[EvidenceUnit],
    risks: list[dict[str, Any]],
    *,
    industry: str,
    product_category: str,
    platform: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not risks:
        return [], []
    warnings: list[str] = []
    try:
        from src.api import CaseRepository, build_query

        risk_text = "；".join(str(risk.get("matched_text", "")) for risk in risks)
        matched_ids = {e for risk in risks for e in risk["evidence_ids"]}
        evidence_text = "；".join(dict.fromkeys(item.text for item in evidence if item.id in matched_ids))[:3000]
        risk_dimensions = list(dict.fromkeys(str(item["risk_dimension"]) for item in risks))
        matched_rule_ids = list(dict.fromkeys(
            str(rule_id)
            for item in risks
            for rule_id in item.get("rule_ids", [])
        ))
        query = build_query({
            "content": f"{risk_text} {evidence_text}".strip(),
            "claim_spans": [],
            "risk_dimensions": risk_dimensions,
            "matched_rule_ids": matched_rule_ids,
        })
        repository = CaseRepository(PROJECT_ROOT / "data", "production", retrieval_mode="lexical")
        if repository.load_error:
            raise RuntimeError(repository.load_error)
        cases = repository.retrieve(
            query,
            top_k=5,
            request_industry=industry,
            product_category=product_category,
            requested_channels=[platform] if platform else [],
            risk_dimensions=risk_dimensions,
            matched_rule_ids=matched_rule_ids,
        )
        for case in cases:
            case["usage_boundary"] = "仅作监管口径参考，不等同于待审视频事实，也不替代人工法律判断。"
        return cases, warnings
    except Exception as exc:  # RAG is non-blocking for the evidence pipeline.
        warnings.append(f"行政处罚案例 RAG 未能加载：{exc}")
        return [], warnings


def analyze_video(
    video_path: str | Path,
    job_dir: str | Path,
    *,
    job_id: str | None = None,
    industry: str = "一般行业",
    product_category: str = "",
    platform: str = "",
    transcript_path: str | Path | None = None,
    transcript_text: str | None = None,
    sample_interval: float = 0.5,
    max_frames: int = 1800,
    asr_mode: str = "auto",
    sampling_strategy: str = "adaptive",
    semantic_mode: str = "auto",
    proof_paths: list[Path] | None = None,
    product_name: str = "",
    product_id: str = "",
    activity_text: str = "",
    landing_page_text: str = "",
    cloud_consent_endpoint: str = "",
    progress=None,
) -> dict[str, Any]:
    """Run the evidence-first video compliance MVP.

    The function intentionally returns candidates only.  It never concludes that
    an advertisement is legally compliant or that intellectual-property rights
    have or have not been licensed.
    """

    video = Path(video_path).resolve()
    destination = Path(job_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    frames_dir = destination / "frames"
    frames_dir.mkdir(exist_ok=True)
    if not video.is_file():
        raise FileNotFoundError(video)
    if not math.isfinite(sample_interval) or sample_interval <= 0:
        raise ValueError("sample_interval 必须大于 0")
    if max_frames <= 0:
        raise ValueError("max_frames 必须大于 0")

    if asr_mode not in {"auto", "off"}:
        raise ValueError("asr_mode must be auto or off")
    if progress:
        progress("正在识别音轨并进行自适应抽帧与 OCR")
    # Audio and visual processing are independent; audio failures retain visual evidence.
    with ThreadPoolExecutor(max_workers=2) as executor:
        audio_future = executor.submit(transcribe_video, video, destination) if asr_mode == "auto" else None
        try:
            native_result = extract_video_frames(video, frames_dir, sample_interval=sample_interval,
                max_frames=max_frames, sampling_strategy=sampling_strategy)
        except Exception as exc:
            native_result = {"duration": 0., "frames": [], "errors": [{"stage": "vision", "message": str(exc)}]}
        audio_units, audio_status = audio_future.result() if audio_future else ([], {"status": "disabled", "segment_count": 0})
    if progress:
        progress("音视频识别完成，正在匹配规则并检索处罚案例")
    _write_json(destination / "native_ocr_raw.json", native_result)
    duration = max(0.0, float(native_result.get("duration", 0.0)),
                   max((u.t_end for u in audio_units), default=0.))
    frames = native_result.get("frames", [])
    expected_frames = min(max_frames, max(1, int(math.ceil(duration / sample_interval)))) if duration else 0
    frame_count = len(frames)
    last_timestamp = max((float(frame.get("timestamp", 0.0)) for frame in frames), default=0.0)
    duration_covered = bool(frames) and (duration <= sample_interval or last_timestamp + sample_interval >= duration - 0.05)
    truncated_by_limit = bool(duration and math.ceil(duration / sample_interval) > max_frames)
    sampling = native_result.get("sampling", {})
    coverage_complete = (bool(sampling["sampling_complete"]) if sampling else
                         bool(frame_count >= expected_frames > 0 and duration_covered and not truncated_by_limit))

    warnings: list[str] = []
    if truncated_by_limit:
        warnings.append("抽帧触及 max_frames 上限，部分采样点被省略；需增加预算或分段复审。")
    if not coverage_complete:
        warnings.append("画面采样未覆盖完整时长；不得据此出具无风险结论。")
    if sample_interval > 1.0:
        warnings.append(
            f"当前按 {sample_interval:g} 秒间隔抽帧；帧间短暂出现的文字或标识可能漏检。"
        )
    if "fallback" in str(native_result.get("engine", "")).lower():
        warnings.append(
            "AVFoundation 未能解码该视频，已使用 OpenCV 抽帧并继续使用 Apple Vision OCR；"
            "处理引擎已在清单留痕。"
        )
    extraction_error_count = len(native_result.get("errors", []))
    ocr_error_count = sum(
        1
        for frame in frames
        for observation in frame.get("ocr", [])
        if observation.get("error")
    )
    if extraction_error_count and not coverage_complete:
        warnings.append(f"抽帧过程中记录到 {extraction_error_count} 个错误，画面覆盖状态未获证明。")
    if ocr_error_count:
        warnings.append(
            f"有 {ocr_error_count} 个采样画面的 OCR 执行失败；"
            "不得据此判断对应画面无文字风险。"
        )
        coverage_complete = False
    if sampling.get("omitted_candidates"):
        warnings.append(f"预算不足：省略 {sampling['omitted_candidates']} 个候选采样点，已保留全时长基线，仍需补审。")
    if not frames:
        warnings.append("视频画面识别失败；当前报告只能使用可用的音轨或用户文本。")
    if audio_status["status"] in {"failed", "partial", "disabled", "no_speech_detected"}:
        warnings.append("口播覆盖不足：" + audio_status["status"] + "；" + audio_status.get("error", "请检查音轨、模型或补充人工转写。"))
    if audio_status.get("low_confidence_segments"):
        warnings.append(f"{len(audio_status['low_confidence_segments'])} 段口播置信度低于 0.6，报告列出时间戳，请回听原视频。此分数不是法律风险概率。")
    if audio_units:
        warnings.append("口播为机器转写，即使置信度较高也可能有错字或漏词；关键主张须回听。sampled_complete 仅表示采样流程完成，不代表识别正确或内容合规。")
    if audio_status.get("engine_disagreements"):
        warnings.append(f"中文与独立语音引擎在 {len(audio_status['engine_disagreements'])} 个片段存在分歧，原始结果均已保留，请回听。")
    if audio_status.get("fallback_reason"):
        warnings.append(audio_status["fallback_reason"])
    if sampling.get("limitation"):
        warnings.append(sampling["limitation"])

    ocr_units = _ocr_evidence(native_result, duration, sample_interval)
    resolved_transcript = Path(transcript_path).resolve() if transcript_path else None
    transcript_units, transcript_warnings = transcript_evidence(
        transcript_path=resolved_transcript,
        transcript_text=transcript_text or "",
        duration=duration,
    )
    warnings.extend(w for w in transcript_warnings if transcript_units or audio_status["status"] not in {"transcribed", "silent", "no_audio_track"})
    evidence = ocr_units + audio_units + transcript_units
    audio_covered = audio_status["status"] in {"transcribed", "silent", "no_audio_track"}
    coverage = {"visual": {"status": "sampled_complete" if coverage_complete else "incomplete",
                           "sample_count": frame_count, "ocr_failed_frames": ocr_error_count, **sampling},
                "audio": audio_status,
                "provided_transcript": {"segments": len(transcript_units), "provenance": "user_supplied_not_audio_verified"}}
    complete = coverage_complete and audio_covered and not audio_status.get("low_confidence_segments") and not audio_status.get("engine_disagreements") and audio_status.get("quality_status") != "verification_failed"

    risk_items, check_items = analyze_rules(
        evidence,
        industry=industry,
        frame_count=frame_count,
        coverage_complete=coverage_complete,
        sample_interval=sample_interval,
    )
    risks = [item.to_dict() for item in risk_items]
    requirement_checks = [item.to_dict() for item in check_items]
    if progress:
        progress("正在进行画面语义、证明材料、活动条件和平台规则核验")
    from .semantics import analyze_scenes
    from .materials import ingest_materials, verify_materials
    from .platform_check import check_platforms
    semantics = analyze_scenes(frames, destination, semantic_mode, video_sha256=_sha256(video),
                              transcript=audio_units, consent_endpoint=cloud_consent_endpoint)
    materials = ingest_materials(proof_paths or [], destination, activity_text, landing_page_text)
    material_verification = verify_materials(evidence, risks, materials, product_name=product_name,
                                            product_id=product_id, landing_page_text=landing_page_text)
    platform_verification = check_platforms(evidence, risks, semantics, platform=platform, industry=industry,
                                            product_category=product_category, landing_page_text=landing_page_text)
    if semantics["status"] != "analyzed":
        warnings.append("画面语义未完整执行，见语义模块状态及错误。")
    if material_verification["checks"]:
        warnings.append("产品证明及活动条件需复核；上传材料不等于真实性、效力或实际兑现已验证。")
    warnings.extend(platform_verification["warnings"])
    cases, rag_warnings = _retrieve_cases(
        evidence,
        risks,
        industry=industry,
        product_category=product_category,
        platform=platform,
    )
    warnings.extend(rag_warnings)

    severity_counts = {
        level: sum(1 for item in risks if item.get("severity") == level)
        for level in ("high", "medium", "low")
    }
    report: dict[str, Any] = {
        "schema_version": "video-mvp-report/v3",
        "visual_semantics": semantics,
        "material_verification": material_verification,
        "platform_verification": platform_verification,
        "review_readiness": "human_review_required",
        "job_id": job_id or destination.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "pending_human_review",
        "coverage_status": "sampled_complete" if complete else "not_proven",
        "coverage": coverage,
        "analysis_status": "completed" if complete and semantics["status"] == "analyzed" else "needs_attention",
        "rule_engine": {"version": pattern_catalog()["version"], "patterns": len(pattern_catalog()["patterns"]),
                        "status": pattern_catalog()["status"]},
        "manual_review_tasks": [
            "核对低置信度口播、专有名词与多人重叠语音。",
            "确认产品分类、资质、注册备案/审查样件和证明材料。",
            "复核画面语义观察、双引擎转写分歧、被省略的代表帧和动作过程。",
            "核验材料真实性、主张支持范围、活动实际兑现和平台规则当前生效版本。",
        ],
        "transcript": [e.to_dict() for e in audio_units + transcript_units],
        "scope": {
            "product_name": product_name,
            "product_id": product_id,
            "industry": industry,
            "product_category": product_category,
            "platform": platform,
            "sample_interval_seconds": sample_interval,
        },
        "summary": {
            "risk_candidates": len(risks),
            "severity_counts": severity_counts,
            "requirement_checks": len(requirement_checks),
            "ocr_evidence_units": len(ocr_units),
            "transcript_evidence_units": len(transcript_units) + len(audio_units),
            "reference_cases": len(cases),
        },
        "risks": risks,
        "requirement_checks": requirement_checks,
        "reference_cases": cases,
        "warnings": list(dict.fromkeys(warnings)),
        "capability_boundaries": {
            "implemented": [
                "本机视频抽帧与 OCR",
                "本地无字幕音轨转写与句词时间戳（实际状态见口播覆盖）",
                "基线、局部画面变化、切换前后和尾帧自适应采样",
                "上传字幕/转写文本的时序解析",
                "广告法绝对化用语候选",
                "保健食品疾病功效与必要展示项候选",
                "跨行业效果、背书、赠送承诺与不当表达的文字线索",
                "中文专用语音与独立引擎核对（实际状态见音轨模块）",
                "画面语义观察接口（是否执行见语义模块）",
                "证明材料文本、主体/日期/范围、活动条件与数量一致性检查",
                "平台条款候选关联及来源完整性、生效状态检查",
                "行政处罚案例 RAG 参考",
                "可定位时间点和画面框的证据报告",
            ],
            "not_connected": [
                "音乐曲库/授权链核验",
                "视频 DNA/版权库比对",
                "IP 形象权利库比对",
                "字体版权识别",
                "证明材料官方验真、功效事实确证与活动实际兑现",
                "说话人分离与身份识别",
            ],
        },
        "disclaimer": (
            "本报告基于抽帧、OCR、音轨转写、用户提供文本及规则/案例库生成风险线索，"
            "不构成法律意见、合规结论或授权状态证明。所有命中与未命中均须人工复核。"
        ),
    }

    evidence_payload = {
        "schema_version": "video-mvp-evidence/v1",
        "job_id": report["job_id"],
        "items": [item.to_dict() for item in evidence],
    }
    _write_json(destination / "evidence.json", evidence_payload)
    _write_json(destination / "report.json", report)

    transcript_source = resolved_transcript
    manifest = {
        "schema_version": "video-mvp-manifest/v1",
        "job_id": report["job_id"],
        "created_at": report["created_at"],
        "source": {
            "file_name": video.name,
            "sha256": _sha256(video),
            "bytes": video.stat().st_size,
            "duration_seconds": duration,
        },
        "transcript_source": (
            {
                "file_name": transcript_source.name,
                "sha256": _sha256(transcript_source),
                "bytes": transcript_source.stat().st_size,
            }
            if transcript_source and transcript_source.is_file()
            else {"inline": bool(transcript_text), "sha256": hashlib.sha256((transcript_text or "").encode()).hexdigest()}
            if transcript_text
            else None
        ),
        "extraction": {
            "engine": native_result.get("engine", "AVFoundation + Apple Vision"),
            "sample_interval_seconds": sample_interval,
            "max_frames": max_frames,
            "frame_count": frame_count,
            "expected_frame_count": expected_frames,
            "last_timestamp_seconds": last_timestamp,
            "truncated_by_limit": truncated_by_limit,
            "coverage_complete": coverage_complete,
            "sampling": sampling,
            "audio_status": audio_status,
        },
        "artifacts": {
            "semantic_raw_sha256": _sha256(destination / "semantic_raw.json"),
            "materials_sha256": _sha256(destination / "materials.json"),
            "platform_catalog_sha256": _sha256(PROJECT_ROOT / "data/platform_rules/structured_candidates/2026-09-04/beauty_platform_rule_candidates.json") if (PROJECT_ROOT / "data/platform_rules/structured_candidates/2026-09-04/beauty_platform_rule_candidates.json").is_file() else None,
            "native_ocr_raw": "native_ocr_raw.json",
            "native_ocr_raw_sha256": _sha256(destination / "native_ocr_raw.json"),
            "asr_raw_sha256": _sha256(destination / "asr_raw.json") if (destination / "asr_raw.json").exists() else None,
            "rules_sha256": _sha256(PROJECT_ROOT / "data/rules/video_claim_patterns.json"),
            "evidence": "evidence.json",
            "evidence_sha256": _sha256(destination / "evidence.json"),
            "report": "report.json",
            "report_sha256": _sha256(destination / "report.json"),
            "report_content_sha256": _json_sha256(report),
        },
        "review_status": "pending_human_review",
    }
    _write_json(destination / "manifest.json", manifest)
    report["artifact_paths"] = {
        "report": str(destination / "report.json"),
        "evidence": str(destination / "evidence.json"),
        "manifest": str(destination / "manifest.json"),
    }
    return report


__all__ = ["VisionExtractionError", "analyze_video"]
