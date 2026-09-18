from __future__ import annotations

import hmac
import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from .worker import estimate_duration_seconds
from .worker import validate_video_file
from .store import JobStore
from .worker import BackgroundWorker

DEFAULT_ROOT = Path(os.getenv("VIDEO_SERVICE_DATA_DIR", Path.cwd() / "data" / "video_service"))
SERVICE_VERSION = "video-service/0.1.0"


def data_root() -> Path:
    return Path(os.getenv("VIDEO_SERVICE_DATA_DIR", str(DEFAULT_ROOT)))


def _api_key() -> str:
    return os.getenv("VIDEO_SERVICE_API_KEY", "")


def require_key(supplied: str | None) -> None:
    key = _api_key()
    if not key:
        raise HTTPException(503, "服务端未配置 VIDEO_SERVICE_API_KEY")
    if not supplied or not hmac.compare_digest(supplied, key):
        raise HTTPException(401, "API Key 无效或缺失")


def command_status() -> dict:
    import shutil as sh
    import subprocess
    commands = {}
    for name in ("ffmpeg", "ffprobe"):
        path = sh.which(name)
        commands[name] = {"ready": bool(path), "path": path}
        if path:
            try:
                out = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=2)
                commands[name]["version"] = (out.stdout.splitlines() or [""])[0]
            except Exception:
                commands[name]["version"] = None
    return commands


def model_status() -> dict:
    try:
        from src.video_mvp.asr import readiness as asr_readiness
        from src.video_mvp.vision import ocr_engine
        from src.video_mvp.cloud_config import public_status
        return {"asr": asr_readiness(), "ocr": ocr_engine(), "vlm": public_status()}
    except Exception as exc:
        return {"error": type(exc).__name__, "message": str(exc)[:200]}


def disk_status(root: Path) -> dict:
    usage = shutil.disk_usage(root)
    min_free = int(os.getenv("VIDEO_SERVICE_MIN_FREE_BYTES", str(2 * 1024 ** 3)))
    return {"free_bytes": usage.free, "total_bytes": usage.total,
            "min_free_bytes": min_free, "ok": usage.free >= min_free}


def create_app() -> FastAPI:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    upload_root = root / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)
    store = JobStore(root / "jobs.sqlite3")
    app = FastAPI(title="Adsure Video Evidence Service", version=SERVICE_VERSION)
    app.state.store = store
    app.state.data_root = root
    worker = BackgroundWorker(store, root)
    worker.start()

    @app.middleware("http")
    async def scrub_secrets(request: Request, call_next):
        response = await call_next(request)
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE_VERSION, "time": int(time.time())}

    @app.get("/ready")
    def ready():
        db_ok = (root / "jobs.sqlite3").exists()
        checks = {
            "commands": command_status(),
            "models": model_status(),
            "data_dir": {"path": str(root), "writable": os.access(root, os.W_OK)},
            "jobs_db": {"path": str(root / "jobs.sqlite3"), "ready": db_ok},
            "rule_engine": {"url_configured": bool(os.getenv("RULE_ENGINE_URL")), "status": "not_checked"},
            "disk": disk_status(root),
        }
        required = [checks["data_dir"]["writable"], db_ok, checks["disk"]["ok"]]
        return JSONResponse(checks, status_code=200 if all(required) else 503)

    @app.post("/api/video/jobs", status_code=202)
    async def create_job(
        video: UploadFile = File(...),
        x_api_key: str | None = Header(default=None),
        record_id: str = Form(""),
        material_id: str = Form(""),
        industry: str = Form("通用"),
        platform: str = Form(""),
        product_category: str = Form(""),
        dedupe_by_hash: bool = Form(True),
    ):
        require_key(x_api_key)
        declared_content_type = (video.content_type or "").lower()
        allowed_mime = {"video/mp4", "video/quicktime", "video/x-m4v", "application/octet-stream"}
        if declared_content_type and declared_content_type not in allowed_mime:
            raise HTTPException(400, "MIME 类型不是受支持的视频格式")
        if not disk_status(root)["ok"]:
            raise HTTPException(507, "磁盘剩余空间不足，拒绝新任务")
        safe_name = Path(video.filename or "upload.mp4").name.replace("\x00", "")
        suffix = Path(safe_name).suffix.lower()
        if suffix not in {".mp4", ".mov", ".m4v"}:
            suffix = ".mp4"
        job_id = uuid.uuid4().hex
        destination = upload_root / f"{job_id}{suffix or '.mp4'}"
        max_bytes = int(os.getenv("VIDEO_SERVICE_MAX_BYTES", str(512 * 1024 * 1024)))
        written = 0
        with destination.open("wb") as handle:
            while chunk := await video.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    destination.unlink(missing_ok=True)
                    raise HTTPException(413, "视频超过大小限制")
                handle.write(chunk)
        try:
            validate_video_file(destination)
            duration = estimate_duration_seconds(destination)
            max_seconds = int(os.getenv("VIDEO_SERVICE_MAX_SECONDS", "1800"))
            if max_seconds and duration > max_seconds:
                raise ValueError(f"视频时长超过 {max_seconds} 秒限制")
        except Exception as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
        import hashlib
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        job, duplicated = store.create_job(source_path=destination, file_sha256=digest,
                                           record_id=record_id, material_id=material_id,
                                           dedupe_by_hash=dedupe_by_hash,
                                           options={"industry": industry, "platform": platform,
                                                    "product_category": product_category})
        if duplicated and destination.exists():
            destination.unlink(missing_ok=True)
        return {"job_id": job["job_id"], "request_id": job["request_id"], "record_id": job["record_id"],
                "material_id": job["material_id"], "status": job["status"], "duplicated": duplicated,
                "evidence_url": f"/api/video/jobs/{job['job_id']}/evidence",
                "result_url": f"/api/video/jobs/{job['job_id']}/result"}

    def _job(job_id: str) -> dict:
        if len(job_id) != 32:
            raise HTTPException(404, "任务不存在")
        try:
            return store.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "任务不存在") from exc

    @app.get("/api/video/jobs/{job_id}")
    def get_job(job_id: str, x_api_key: str | None = Header(default=None)):
        require_key(x_api_key)
        job = _job(job_id)
        return {k: job[k] for k in ("job_id", "record_id", "request_id", "material_id", "status",
                                    "attempts", "error", "created_at", "updated_at", "heartbeat_at")}

    @app.get("/api/video/jobs/{job_id}/evidence")
    def evidence(job_id: str, x_api_key: str | None = Header(default=None)):
        require_key(x_api_key)
        result = store.result(_job(job_id)["job_id"])
        if not result or not result.get("evidence"):
            raise HTTPException(404, "证据尚未生成")
        return result["evidence"]

    @app.get("/api/video/jobs/{job_id}/result")
    def result(job_id: str, x_api_key: str | None = Header(default=None)):
        require_key(x_api_key)
        job = _job(job_id)
        body = store.result(job["job_id"])
        if not body:
            return {"job_id": job_id, "status": job["status"], "evidence": None, "rule_engine": None}
        return body

    return app


app = create_app()
