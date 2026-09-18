# -*- coding: utf-8 -*-
"""视频审核异步任务 API（FastAPI，提交-轮询-结果三段式）。

复用旧 MVP（src/video_mvp/api.py）已与飞书侧联调过的 v0.2 契约：
  POST /api/jobs                      → 202，返回 job_id + poll_url
  GET  /api/jobs/{job_id}             → 轮询状态（terminal / retry_after_ms）
  GET  /api/jobs/{job_id}/audit-response → 飞书 v0.2 结构化结果
  GET  /api/jobs/{job_id}/report      → 前端 review.html 消费的报告 JSON
  GET  /api/jobs/{job_id}/media       → 视频本体（Web 回看用）

与旧 MVP 的关键差异：审核引擎换成本仓库的取证层 + 找法层 + 用法层
（backend/app/pipeline + rules + reasoning），不再是 src/video_mvp 的本机管线。

进度回调：job.json 的 message 字段随阶段更新，轮询接口原样返回 ——
飞书机器人据此刷新卡片文案。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.config import get_settings
from app.pipeline.extract import extract
from app.pipeline.merge import merge_ocr
from app.pipeline.providers.base import CostLimitExceeded, ocr_budget_for
from app.pipeline.providers.local import LocalRapidOCR, LocalWhisperASR
from app.pipeline.evidence import CostRecord, EvidenceBundle, EvidenceSource
from app.reasoning.report import DISCLAIMER, Report, finding_from_hit, finding_from_mandatory
from app.reasoning.subsume import MockLLMProvider, Subsumer, get_llm_provider
from app.rules.mandatory import load_default_checker
from app.rules.matcher import load_default_matcher
from app.feedback import (
    AdjudicationRecord,
    save_adjudication,
)
from app.feedback import FEEDBACK_ROOT as _DEFAULT_FEEDBACK_ROOT

FEEDBACK_ROOT = _DEFAULT_FEEDBACK_ROOT

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOBS_ROOT = Path(os.getenv("ADSURE_JOBS_DIR", PROJECT_ROOT / "data" / "adsure_jobs"))
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
JOB_LOCK = threading.Lock()
CREATE_LOCK = threading.Lock()

# 飞书侧行业名 → 本仓库词库 industry 标识
INDUSTRY_MAP = {
    "美妆": "cosmetics", "化妆品": "cosmetics",
    "游戏": "game",
    "保健食品": "health_food", "普通食品": "health_food",
    "一般行业": "general", "通用": "general",
}
INDUSTRIES = set(INDUSTRY_MAP)
MAX_UPLOAD_MB = int(os.getenv("ADSURE_MAX_UPLOAD_MB", "512"))

LEVEL_CN = {"high": "高", "medium": "中", "low": "低"}
LEVEL_RANK = {"低": 0, "中": 1, "高": 2}
ROUTE_RANK = {"运营": 0, "运营补资料": 1, "法务": 2}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_dir(job_id: str) -> Path:
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    path = (JOBS_ROOT / job_id).resolve()
    if path.parent != JOBS_ROOT.resolve():
        raise HTTPException(status_code=404, detail="任务不存在")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="任务数据不存在") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail="任务数据格式错误")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _job_links(job_id: str) -> dict[str, str]:
    return {
        "poll_url": f"/api/jobs/{job_id}",
        "audit_response_url": f"/api/jobs/{job_id}/audit-response",
        "report_url": f"/api/jobs/{job_id}/report",
        "report_page_url": f"/api/jobs/{job_id}/report-page",
    }


def _poll_state(state: dict) -> dict:
    public_fields = (
        "job_id", "request_id", "record_id", "status", "message", "created_at",
        "started_at", "completed_at", "summary",
    )
    result = {key: state[key] for key in public_fields if key in state}
    terminal = state.get("status") in {"completed", "needs_attention", "failed"}
    result.update(_job_links(state["job_id"]))
    result.update(terminal=terminal, retry_after_ms=0 if terminal else 1500,
                  audit_response_ready=bool(state.get("audit_response_ready")))
    if state.get("status") == "failed":
        result["error"] = state.get("error", "视频审核失败，请使用 job_id 排查服务日志")
    return result


def _find_job_by_request_id(request_id: str) -> str | None:
    for path in sorted(JOBS_ROOT.glob("*/job.json"), reverse=True):
        if not JOB_ID.fullmatch(path.parent.name):
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("request_id") == request_id:
                return path.parent.name
        except (json.JSONDecodeError, OSError):
            continue
    return None


async def _save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    written = 0
    with destination.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="上传文件超过大小限制")
            handle.write(chunk)
    return written


# ── 审核引擎（与 review_video.py 同一条链路，去掉 CLI 部分）────────


def _evidence_json(bundle: EvidenceBundle) -> list[dict]:
    out = []
    for e in bundle.evidences:
        item = {
            "id": getattr(e, "id", ""),
            "source": getattr(getattr(e, "source", None), "value", str(getattr(e, "source", ""))),
            "text": getattr(e, "text", ""),
            "t_start": round(float(getattr(e, "t_start", 0.0)), 3),
            "t_end": round(float(getattr(e, "t_end", 0.0)), 3),
            "confidence": getattr(e, "confidence", None),
            "frame_ids": list(getattr(e, "frame_ids", []) or []),
        }
        bbox = getattr(e, "bbox", None)
        if bbox is not None:
            item["bbox"] = {"x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h}
        fs = getattr(e, "font_scale", None)
        if fs is not None:
            item["font_scale"] = fs
        out.append(item)
    return out


def _findings_json(report: Report) -> list[dict]:
    out = []
    for f in report.findings:
        item = {
            "title": f.title,
            "t_start": round(f.t_start, 3),
            "t_end": round(f.t_end, 3),
            "source": f.source,
            "level": f.level.value,
            "level_label": f.level.label,
            "counts_as_risk": f.counts_as_risk,
            "category": f.category,
            "legal_basis": f.legal_basis,
            "报告": f.to_dict(),
        }
        if f.bbox:
            item["bbox"] = f.bbox
        if f.required_materials:
            item["required_materials"] = list(f.required_materials)
        if f.element_trace:
            item["element_trace"] = f.element_trace
        if f.similar_cases:
            item["similar_cases"] = f.similar_cases
        out.append(item)
    return out


def run_video_review(
    video_path: Path,
    work_dir: Path,
    *,
    industry: str,
    background: str = "",
    llm_mode: str = "auto",
    progress=None,
) -> tuple[dict, dict]:
    """完整审核链路。返回 (报告 payload, 摘要 dict)。

    progress(message) 供异步任务写回 job.json，轮询侧可见。
    """
    def _p(message: str) -> None:
        if progress:
            progress(message)

    settings = get_settings()
    cfg = settings.pipeline

    _p("正在拆解视频（分镜抽帧、pHash 去重）")
    ex = extract(video_path, work_dir, cfg)

    _p(f"正在识别画面文字（{len(ex.frames)} 帧）")
    scaled = ocr_budget_for(ex.meta.duration, cfg.max_ocr_calls_per_video)
    ocr = LocalRapidOCR(max_calls=scaled)
    ocr_ev = ocr.recognize(ex.frames, ex.meta.width, ex.meta.height)

    asr_ev: list = []
    asr_model = None
    if ex.audio_path:
        _p("正在转写口播（字级时间戳）")
        asr = LocalWhisperASR()
        asr_model = asr.model_size
        asr_ev = asr.transcribe(ex.audio_path)

    bundle = EvidenceBundle(
        review_id=video_path.stem,
        video=ex.meta,
        evidences=asr_ev + ocr_ev,
        cost=CostRecord(asr_calls=1 if asr_ev else 0, ocr_calls=ocr.calls_used,
                        frames_sampled=ex.frames_sampled,
                        frames_after_dedup=len(ex.frames)),
    )

    _p("正在合并字幕并匹配规则库")
    bundle.evidences = merge_ocr(list(bundle.evidences), cfg)
    matcher = load_default_matcher()
    hits = matcher.match_bundle(bundle, industry=industry)
    mand = load_default_checker().check_bundle(bundle, industry=industry)

    _p(f"正在进行涵摄推理（{len(hits)} 条命中）")
    if llm_mode == "deepseek":
        llm, mode = get_llm_provider("deepseek"), "deepseek"
    elif settings.llm_configured:
        llm, mode = get_llm_provider(), settings.llm_provider
    else:
        llm, mode = MockLLMProvider(), "mock"

    subsumer = Subsumer(llm=llm)
    report = Report(review_id=bundle.review_id, video_path=video_path.name,
                    duration=bundle.video.duration)
    for h in hits:
        sub, cases = subsumer.subsume_hit(h, background=background, industry=industry)
        report.findings.append(finding_from_hit(h, sub, cases))
    for f in mand:
        report.findings.append(finding_from_mandatory(f))

    usage = getattr(llm, "usage_summary", lambda: "")()
    has_asr = bool(bundle.texts(EvidenceSource.ASR))
    payload = {
        "meta": {
            "review_id": report.review_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "industry": industry,
            "video": {"path": video_path.name,
                      "duration": bundle.video.duration,
                      "width": bundle.video.width, "height": bundle.video.height},
            "llm": {"mode": mode, "is_real": mode != "mock", "usage": usage},
            "lexicon_reviewed_by_legal": bool(
                getattr(getattr(matcher, "lexicon", None), "reviewed_by_legal", False)),
            "data_source": "真实视频 · 本地模型取证"
                           + (f" / ASR {asr_model}" if asr_model else ""),
        },
        "summary": {"level": report.level.value, "level_label": report.level.label,
                    "risk_count": len(report.risks),
                    "advisory_count": len(report.advisories)},
        "cost": {"frames_sampled": bundle.cost.frames_sampled,
                 "frames_after_dedup": bundle.cost.frames_after_dedup,
                 "dedup_ratio": round(bundle.cost.dedup_ratio, 4),
                 "ocr_calls": bundle.cost.ocr_calls,
                 "asr_calls": bundle.cost.asr_calls},
        "evidence": _evidence_json(bundle),
        "findings": _findings_json(report),
        "disclaimer": DISCLAIMER,
    }
    summary = {"level": report.level.label, "risk_count": len(report.risks),
               "advisory_count": len(report.advisories)}
    return payload, summary


# ── 飞书 v0.2 契约适配 ─────────────────────────────────────────


def _stable_rule_uid(rule_id: str) -> str:
    return hashlib.sha256(f"adsure-rule|{rule_id}".encode()).hexdigest()[:24]


# 绝对化用语常见词面（与 L1 词库一致的核心词），用于 finding → 规则映射
_ABSOLUTE_TERMS = ("国家级", "最高级", "最佳", "第一", "顶级", "独家", "全网第一",
                   "销量第一", "最新", "最先进", "最优惠")


def _fallback_rule_id(finding: dict) -> str:
    title = finding.get("title", "")
    rep = finding.get("报告", {})
    blob = title + rep.get("风险表达", "") + rep.get("违规类型", "")
    category = finding.get("category", "")
    if "必备" in category or "显著" in category or "可识别" in title:
        return "ADLAW-018-02"
    if any(term in blob for term in _ABSOLUTE_TERMS) or "绝对化" in blob:
        return "ADLAW-009-03"
    if "疾病" in blob or "根治" in blob or "治疗" in blob:
        return "ADLAW-018-01-02"
    return "ADLAW-028"


def _video_rule(finding: dict) -> dict:
    """报告 finding → 飞书 matched_rules 条目。"""
    level = LEVEL_CN.get(finding.get("level", "low"), "中")
    needs_material = bool(finding.get("required_materials"))
    route = "运营补资料" if needs_material else ("法务" if level == "高" else "运营")
    rep = finding.get("报告", {})
    rule_id = _fallback_rule_id(finding)
    return {
        "rule_id": rule_id,
        "rule_uid": _stable_rule_uid(rule_id),
        "title": finding.get("title", "视频风险候选"),
        "dimension": finding.get("category", "其他"),
        "risk_level": level,
        "judgment": "视频审核生成风险候选，需结合原视频、语境和事实材料人工判断",
        "match_reason": rep.get("风险表达", finding.get("title", "")),
        "default_routing": route,
        "legal_basis": [finding.get("legal_basis", "")] if finding.get("legal_basis") else [],
        "applicability_status": "needs_fact_verification",
        "confidence": None,
        "material_evidence": rep.get("风险表达", ""),
        "satisfied_elements": ["视频审核报告存在可回溯的机器证据或核验缺口"],
        "unsatisfied_elements": ["尚未完成人工语境、事实及规则适用性核验"],
        "missing_facts": list(finding.get("required_materials", [])) or ["完整投放语境"],
        "applicability_reason": rep.get("风险定性", "机器结果不构成违法认定。"),
        "serial_no": None,
    }


def _aggregate_matched(matched: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in matched:
        current = unique.get(item["rule_id"])
        if current is None:
            unique[item["rule_id"]] = item
            continue
        for key, sep in (("title", "；"), ("dimension", "、"), ("match_reason", "；"),
                         ("material_evidence", "\n"), ("applicability_reason", "；")):
            values = list(dict.fromkeys(filter(None, [current.get(key, ""), item.get(key, "")])))
            current[key] = sep.join(values)
        for key in ("legal_basis", "satisfied_elements", "unsatisfied_elements", "missing_facts"):
            current[key] = list(dict.fromkeys(current.get(key, []) + item.get(key, [])))
        if ROUTE_RANK[item["default_routing"]] > ROUTE_RANK[current["default_routing"]]:
            current["default_routing"] = item["default_routing"]
        if LEVEL_RANK[item["risk_level"]] > LEVEL_RANK[current["risk_level"]]:
            current["risk_level"] = item["risk_level"]
    result = list(unique.values())
    for serial, item in enumerate(result, 1):
        item["serial_no"] = serial
    return result


def build_feishu_response(report_payload: dict, state: dict,
                          *, now_ms: int | None = None) -> dict:
    """新引擎报告 → 飞书 v0.2 audit-response。字段与旧契约一一对应。"""
    findings = report_payload.get("findings", [])
    risks = [f for f in findings if f.get("counts_as_risk")]
    matched = _aggregate_matched([_video_rule(f) for f in risks])

    types = list(dict.fromkeys(f.get("category", "其他") for f in risks if f.get("category")))
    highest = max((r["risk_level"] for r in matched),
                  key=lambda x: LEVEL_RANK.get(x, 0), default="低")
    pre_level = highest if matched else "无明显风险"
    routing = "法务" if any(r["default_routing"] == "法务" for r in matched) else "运营"
    words = list(dict.fromkeys(
        w for f in risks for w in re.findall(r"「([^」]+)」", f.get("title", "")) ))

    if matched:
        summary = "；".join(r["match_reason"] for r in matched)[:80]
        advice_items = list(dict.fromkeys(
            f.get("报告", {}).get("修改建议", "") for f in risks
            if f.get("报告", {}).get("修改建议")))
        advice = "；".join(advice_items)[:100] or "结合原视频和所列缺失事实完成人工复核。"
    else:
        summary = "未命中当前规则库的风险候选，不代表无风险；仍需结合完整素材和行业规则人工复核"[:80]
        advice = "复核完整视频、口播、画面、产品材料和平台现行规则后再决定投放。"[:100]

    bases = list(dict.fromkeys(
        x for r in matched for x in r.get("legal_basis", []) if x))
    opinion = (
        f"①风险定性：视频审核生成{len(matched)}项规则或核验候选；不构成违法认定。\n"
        f"②违禁词鉴别：{'、'.join(words) if words else '当前可用文字证据未命中字面高风险词；不代表无风险'}。\n"
        f"③违规类型：{'、'.join(types) if types else '暂未形成类型候选'}。\n"
        f"④法律依据：{'；'.join(bases) if bases else '未形成自动适用结论'}。\n"
        f"⑤修改建议：{advice}\n"
        f"⑥风险定级：预审{pre_level}、法务推荐{highest}；结论待人工复核。")

    timestamp = int(now_ms if now_ms is not None else datetime.now().timestamp() * 1000)
    meta = report_payload.get("meta", {})
    return {
        "request_id": state.get("request_id") or state.get("record_id")
                      or report_payload.get("meta", {}).get("review_id", ""),
        "resolved_mode": "标准",
        "mode_reason": "",
        "预审_风险等级": pre_level,
        "预审_命中要点": summary,
        "预审_修改建议": advice,
        "预审_时间": timestamp,
        "审核_审核意见": opinion,
        "审核_关键实体抽取": meta.get("video", {}).get("path", "无"),
        "审核_高风险词命中": "，".join(words) or "无",
        "审核_备案核查结果": "视频审核不涉及材料备案核查；需核验条目见 matched_rules.missing_facts",
        "审核_推荐违规类型": types,
        "审核_推荐风险等级": highest,
        "matched_rules": matched,
        "审核_审核时间": timestamp,
        "routing": routing,
        "audit_time": timestamp,
        "审核_平台规则预检": "视频审核暂未接入平台规则预检",
        "context_package": {
            "contract_version": "0.2",
            "source": "adsure_evidence_layer_v1",
            "job_id": state.get("job_id"),
            "industry": meta.get("industry"),
            "llm_mode": meta.get("llm", {}).get("mode"),
            "cost": report_payload.get("cost"),
            "human_review_required": True,
        },
    }


# ── 异步任务执行 ───────────────────────────────────────────────


def _process_job(job_id: str) -> None:
    with JOB_LOCK:
        _run_job(job_id)


def _run_job(job_id: str) -> None:
    directory = _job_dir(job_id)
    state_path = directory / "job.json"
    state = _read_json(state_path)
    state.update({"status": "processing", "started_at": _now(),
                  "message": "正在拆解视频"})
    _write_json(state_path, state)

    def progress(message: str) -> None:
        state["message"] = message
        _write_json(state_path, state)

    try:
        payload, summary = run_video_review(
            directory / state["video_file"],
            directory / "_work",
            industry=state["industry"],
            background=state.get("supplement", ""),
            llm_mode="auto",
            progress=progress,
        )
        (directory / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        response = build_feishu_response(payload, state)
        (directory / "audit_response.json").write_text(
            json.dumps({"code": 0, "msg": "ok", "data": response},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        digest = hashlib.sha256((directory / "audit_response.json").read_bytes()).hexdigest()
        (directory / "manifest.json").write_text(json.dumps({
            "job_id": job_id,
            "artifacts": {"feishu_audit_response_sha256": digest,
                          "report_sha256": hashlib.sha256(
                              (directory / "report.json").read_bytes()).hexdigest()},
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        state.update({
            "status": "completed" if summary["risk_count"] else "needs_attention",
            "completed_at": _now(),
            "message": "审核完成" if summary["risk_count"] else "审核完成，未命中风险候选",
            "summary": summary,
            "audit_response_ready": True,
        })
        _write_json(state_path, state)
    except CostLimitExceeded as exc:
        state.update({"status": "failed", "completed_at": _now(),
                      "error": f"成本红线：{exc}", "message": "触发成本红线，已停止"})
        _write_json(state_path, state)
    except Exception as exc:  # noqa: BLE001 — 任务失败必须落状态，不能静默
        logger.exception("job %s failed", job_id)
        state.update({"status": "failed", "completed_at": _now(),
                      "error": f"{type(exc).__name__}: {exc}"[:300],
                      "message": "审核失败"})
        _write_json(state_path, state)


# ── FastAPI 应用 ───────────────────────────────────────────────


def create_app() -> FastAPI:
    application = FastAPI(title="审心 Adsure · 视频合规审核", version="1.0.0")
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)

    @application.get("/health")
    def health() -> dict[str, Any]:
        settings = get_settings()
        return {
            "status": "ok",
            "service": "adsure-video-review",
            "engine": "evidence-layer-v1",
            "llm": {"mode": settings.llm_provider,
                    "configured": settings.llm_configured},
            "feishu_contract": {
                "version": "0.2",
                "upload": "/api/jobs",
                "poll": "/api/jobs/{job_id}",
                "result": "/api/jobs/{job_id}/audit-response",
            },
            "jobs_dir": str(JOBS_ROOT),
        }

    @application.post("/api/jobs", status_code=202)
    async def create_job(
        background_tasks: BackgroundTasks,
        video: UploadFile = File(...),
        industry: str = Form("一般行业"),
        supplement: str = Form(""),
        record_id: str = Form(""),
        platform: str = Form(""),
        platforms_json: str = Form(""),
    ) -> dict[str, Any]:
        video_name = Path(video.filename or "video.mp4").name
        suffix = Path(video_name).suffix.lower()
        if suffix not in ALLOWED_VIDEO_SUFFIXES:
            raise HTTPException(status_code=400, detail="仅支持 MP4、MOV 或 M4V 视频")
        industry_key = INDUSTRY_MAP.get(industry.strip())
        if industry_key is None:
            raise HTTPException(
                status_code=400,
                detail=f"暂不支持该行业。可用：{'、'.join(sorted(INDUSTRY_MAP))}")
        if len(supplement) > 30000:
            raise HTTPException(status_code=400, detail="补充背景长度超过上限")
        record_id = record_id.strip()
        if len(record_id) > 128:
            raise HTTPException(status_code=400, detail="record_id 无效或超过 128 字符")

        max_upload = MAX_UPLOAD_MB * 1024 * 1024
        job_id = uuid.uuid4().hex
        request_id = record_id or job_id
        with CREATE_LOCK:
            existing = _find_job_by_request_id(request_id) if record_id else None
            if existing:
                previous = _read_json(_job_dir(existing) / "job.json")
                return {"job_id": existing, "request_id": request_id,
                        "status": previous.get("status", "queued"),
                        "deduplicated": True, **_job_links(existing)}
            directory = JOBS_ROOT / job_id
            directory.mkdir(parents=True)
            _write_json(directory / "job.json", {
                "job_id": job_id, "request_id": request_id,
                "record_id": record_id or None, "status": "uploading",
                "message": "正在接收视频", "created_at": _now(),
                "audit_response_ready": False,
            })
        try:
            stored = "source" + suffix
            byte_count = await _save_upload(video, directory / stored, max_upload)
            if byte_count == 0:
                raise HTTPException(status_code=400, detail="视频文件为空")
            _write_json(directory / "job.json", {
                "job_id": job_id, "request_id": request_id,
                "record_id": record_id or None,
                "status": "queued", "message": "已上传，等待审核",
                "created_at": _now(),
                "original_file_name": video_name,
                "video_file": stored, "video_bytes": byte_count,
                "industry": industry_key,
                "platform": platform.strip(),
                "supplement": supplement,
                "audit_response_ready": False,
            })
            background_tasks.add_task(_process_job, job_id)
            return {"job_id": job_id, "request_id": request_id,
                    "status": "queued", "deduplicated": False,
                    **_job_links(job_id)}
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    @application.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        return _poll_state(_read_json(_job_dir(job_id) / "job.json"))

    @application.get("/api/jobs/{job_id}/audit-response")
    def audit_response(job_id: str) -> JSONResponse:
        directory = _job_dir(job_id)
        path = directory / "audit_response.json"
        if path.is_file():
            return JSONResponse(_read_json(path))
        state = _read_json(directory / "job.json")
        if state.get("status") == "failed":
            return JSONResponse(status_code=500,
                                content={"code": -1, "msg": "视频审核失败，请使用 job_id 排查",
                                         "data": None})
        return JSONResponse(status_code=409,
                            content={"code": -1,
                                     "msg": "视频审核尚未完成，请按 poll_url 继续轮询",
                                     "data": None})

    @application.get("/api/jobs/{job_id}/report")
    def report(job_id: str) -> JSONResponse:
        return JSONResponse(_read_json(_job_dir(job_id) / "report.json"))

    @application.post("/api/jobs/{job_id}/adjudication", status_code=201)
    def adjudicate(job_id: str, body: dict) -> dict[str, Any]:
        """法务裁决回流（手册 Step6：裁决结果沉淀回规则库/类案库/IP 底库）。

        body: {"finding_index": 0, "action": "false_positive",
               "reason": "...", "adjudicator": "法务-张某"}
        action 枚举见 app.feedback.AdjudicationRecord。
        裁决的定位字段（title/t_start/source/matched_text）从已生成的
        report.json 读取，防止调用方传错导致回流数据对不上原始证据。
        """
        directory = _job_dir(job_id)
        report_path = directory / "report.json"
        if not report_path.is_file():
            raise HTTPException(status_code=409, detail="报告尚未生成，无法裁决")
        findings = _read_json(report_path).get("findings", [])
        idx = body.get("finding_index")
        if not isinstance(idx, int) or not (0 <= idx < len(findings)):
            raise HTTPException(
                status_code=400,
                detail=f"finding_index 必须是 0–{len(findings)-1} 的整数")
        action = body.get("action", "")
        allowed = {"confirmed_violation", "false_positive", "missed_risk",
                   "not_applicable", "needs_more_evidence",
                   "ip_confirmed", "ip_rejected"}
        if action not in allowed:
            raise HTTPException(status_code=400,
                                detail=f"action 必须是：{'、'.join(sorted(allowed))}")

        f = findings[idx]
        rep = f.get("报告", {})
        record = AdjudicationRecord(
            job_id=job_id,
            finding_index=idx,
            title=f.get("title", ""),
            t_start=float(f.get("t_start", 0) or 0),
            t_end=float(f.get("t_end", 0) or 0),
            source=f.get("source", ""),
            action=action,
            reason=str(body.get("reason", ""))[:2000],
            adjudicator=str(body.get("adjudicator", ""))[:100],
            ip_id=body.get("ip_id"),
            entity_name=body.get("entity_name"),
            matched_text=body.get("matched_text", ""),
            context=rep.get("风险表达", ""),
        )
        path = save_adjudication(record, root=FEEDBACK_ROOT)
        return {"status": "recorded", "feedback_file": path.name,
                "feedback_kind": record.feedback_kind,
                "adjudicated_at": record.adjudicated_at}

    @application.get("/api/jobs/{job_id}/report-page")
    def report_page(job_id: str) -> FileResponse:
        """前端 review.html 静态页。?report= 参数指向本 job 的 report 接口。"""
        page = PROJECT_ROOT / "frontend" / "review.html"
        if not page.is_file():
            raise HTTPException(status_code=404, detail="前端页面未部署")
        return FileResponse(page, media_type="text/html")

    @application.get("/api/jobs/{job_id}/media")
    def media(job_id: str) -> FileResponse:
        directory = _job_dir(job_id)
        state = _read_json(directory / "job.json")
        video_path = directory / str(state.get("video_file", ""))
        if not video_path.is_file():
            raise HTTPException(status_code=404, detail="视频不存在")
        return FileResponse(video_path, media_type="video/mp4",
                            filename=state.get("original_file_name"))

    return application


app = create_app()
