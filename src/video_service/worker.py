from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from .extractor import extract_video
from .rule_engine import invoke_rule_engine
from .schemas import EvidenceBundle
from .store import JobStore

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v"}
SIGNATURES = (b"\x00\x00\x00\x18ftyp", b"\x00\x00\x00\x1cftyp", b"\x00\x00\x00\x20ftyp")


def validate_video_file(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("仅支持 MP4/MOV/M4V")
    with path.open("rb") as handle:
        header = handle.read(16)
    if not header:
        raise ValueError("视频文件为空")
    # ISO BMFF files contain ftyp at byte 4; MOV/MP4 family.
    if header[4:8] != b"ftyp":
        raise ValueError("文件头不是 MP4/MOV 视频")


def estimate_duration_seconds(path: Path) -> float:
    try:
        import av
        with av.open(str(path)) as container:
            if not container.streams.video:
                raise ValueError("文件不含视频流")
            return float(container.duration / av.time_base) if container.duration else 0.0
    except Exception as exc:
        raise ValueError(f"视频解码失败：{type(exc).__name__}") from exc


def _build_result(job: dict, bundle: EvidenceBundle | None, rule_result, status: str,
                  error: str | None) -> dict:
    return {
        "job_id": job["job_id"],
        "record_id": job["record_id"],
        "request_id": job["request_id"],
        "material_id": job["material_id"],
        "status": status,
        "evidence": bundle.model_dump(mode="json") if bundle else None,
        "rule_engine": rule_result.model_dump(mode="json") if rule_result else {
            "status": "skipped", "request_id": job["request_id"]},
        "warnings": bundle.warnings if bundle else [],
        "error": error,
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def process_once(store: JobStore, data_root: Path) -> bool:
    stale = int(os.getenv("VIDEO_SERVICE_STALE_SECONDS", "900"))
    job = store.claim_next(stale)
    if not job:
        return False
    source = Path(job["source_path"])
    work_dir = data_root / "jobs" / job["job_id"]
    work_dir.mkdir(parents=True, exist_ok=True)
    options = json.loads(job.get("options_json") or "{}")
    bundle = None
    rule_result = None
    try:
        validate_video_file(source)
        max_bytes = int(os.getenv("VIDEO_SERVICE_MAX_BYTES", str(512 * 1024 * 1024)))
        if source.stat().st_size > max_bytes:
            raise ValueError("视频超过大小限制")
        max_seconds = int(os.getenv("VIDEO_SERVICE_MAX_SECONDS", "1800"))
        duration = estimate_duration_seconds(source)
        if max_seconds and duration > max_seconds:
            raise ValueError(f"视频时长超过 {max_seconds} 秒限制")
        bundle = extract_video(
            record_id=job["record_id"], request_id=job["request_id"],
            material_id=job["material_id"], video_path=source, work_dir=work_dir,
            industry=options.get("industry") or os.getenv("VIDEO_SERVICE_INDUSTRY", "通用"),
            platform=options.get("platform") or os.getenv("VIDEO_SERVICE_PLATFORM", ""),
            product_category=options.get("product_category", ""),
        )
        rule_result = invoke_rule_engine(bundle)
        if rule_result.status == "completed":
            bundle.coverage.rule_engine.status = "completed"
        elif rule_result.status == "skipped":
            bundle.coverage.rule_engine.status = "not_configured"
        else:
            bundle.coverage.rule_engine.status = "failed"
            bundle.warnings.append("规则引擎不可用；未生成最终审核判断，需恢复后重试。")
        (work_dir / "evidence.protocol.json").write_text(
            bundle.model_dump_json(indent=2), encoding="utf-8")
        status = "completed" if rule_result.status == "completed" else "partial"
        result = _build_result(job, bundle, rule_result, status, None)
        store.finish(job["job_id"], status, result, bundle.warnings, None)
    except Exception as exc:
        error = f"{type(exc).__name__}:{str(exc)[:300]}"
        fallback = "partial" if bundle else "failed"
        result = _build_result(job, bundle, rule_result, fallback, error)
        if bundle:
            store.finish(job["job_id"], fallback, result, bundle.warnings, error)
        else:
            store.requeue_or_fail(job["job_id"], error)
    return True


def run_worker(store: JobStore, data_root: Path, *, once: bool = False) -> None:
    interval = float(os.getenv("VIDEO_SERVICE_POLL_INTERVAL", "1"))
    while True:
        try:
            worked = process_once(store, data_root)
        except Exception:
            worked = False
        if once:
            return
        time.sleep(0 if worked else interval)


class BackgroundWorker:
    def __init__(self, store: JobStore, data_root: Path):
        self.store = store
        self.data_root = data_root
        self.thread = None
        self.stop = threading.Event()

    def _loop(self):
        while not self.stop.is_set():
            run_worker(self.store, self.data_root)
            self.stop.wait(float(1.0))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="video-service-worker", daemon=True)
        self.thread.start()
