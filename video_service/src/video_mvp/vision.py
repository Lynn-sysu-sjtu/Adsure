from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from .env_config import load_env


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NATIVE_SOURCE = Path(__file__).with_name("native_vision.m")
DEFAULT_BINARY = PROJECT_ROOT / "tmp" / "video_mvp" / "adsure_vision"
OCR_CONFIG_NAMES = {"VIDEO_MVP_OCR_ENGINE"}


class VisionExtractionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ocr_engine() -> str:
    return load_env(OCR_CONFIG_NAMES).get("VIDEO_MVP_OCR_ENGINE", "apple_vision").strip().lower()


def _rapidocr_version() -> str:
    try:
        from importlib.metadata import version
        return "rapidocr-onnxruntime/" + version("rapidocr-onnxruntime")
    except Exception:
        return "rapidocr-onnxruntime/unknown"


def _recognize_manifest_rapidocr(manifest: list[dict]) -> dict:
    """Run local RapidOCR over frames selected by the OpenCV sampler."""
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise VisionExtractionError(
            "RapidOCR 未安装：请在 .venv-video 中安装 rapidocr-onnxruntime"
        ) from exc

    engine = RapidOCR()
    frames: list[dict] = []
    errors: list[dict] = []
    provider_version = _rapidocr_version()
    for item in manifest:
        image_path = Path(str(item["imagePath"]))
        pixels = cv2.imread(str(image_path))
        if pixels is None:
            errors.append({"stage": "load_frame", "message": "RapidOCR 无法读取抽取画面",
                           "imagePath": str(image_path)})
            continue
        height, width = pixels.shape[:2]
        observations = []
        try:
            result, _elapsed = engine(str(image_path))
            for recognized in result or []:
                polygon, text, score = recognized[0], str(recognized[1] or "").strip(), recognized[2]
                if not text:
                    continue
                xs = [float(point[0]) for point in polygon]
                ys = [float(point[1]) for point in polygon]
                observations.append({
                    "text": text,
                    "confidence": float(score) if score is not None else None,
                    "bbox": [
                        max(0.0, min(1.0, min(xs) / width)),
                        max(0.0, min(1.0, min(ys) / height)),
                        max(0.0, min(1.0, (max(xs) - min(xs)) / width)),
                        max(0.0, min(1.0, (max(ys) - min(ys)) / height)),
                    ],
                    "provider": "RapidOCR/ONNXRuntime",
                    "provider_version": provider_version,
                })
        except Exception as exc:
            errors.append({"stage": "rapidocr", "message": type(exc).__name__,
                           "imagePath": str(image_path)})
        frames.append({
            "frameId": item["frameId"],
            "timestamp": item["timestamp"],
            "imagePath": str(image_path),
            "width": width,
            "height": height,
            "ocr": observations,
        })
    return {"frames": frames, "errors": errors, "provider_version": provider_version}


def ensure_native_extractor(binary_path: Path = DEFAULT_BINARY) -> Path:
    """Compile the small native extractor when its source changes."""

    binary_path.parent.mkdir(parents=True, exist_ok=True)
    stamp_path = binary_path.with_suffix(".source.sha256")
    source_digest = _sha256(NATIVE_SOURCE)
    if binary_path.exists() and stamp_path.exists():
        if stamp_path.read_text(encoding="utf-8").strip() == source_digest:
            return binary_path

    command = [
        "/usr/bin/clang",
        "-fobjc-arc",
        str(NATIVE_SOURCE),
        "-o",
        str(binary_path),
        f"-fmodules-cache-path={binary_path.parent / 'module-cache'}",
        "-framework",
        "Foundation",
        "-framework",
        "AVFoundation",
        "-framework",
        "CoreGraphics",
        "-framework",
        "CoreMedia",
        "-framework",
        "Vision",
        "-framework",
        "ImageIO",
        "-framework",
        "UniformTypeIdentifiers",
        "-mmacosx-version-min=12.0",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        raise VisionExtractionError(
            "native extractor compilation failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    stamp_path.write_text(source_digest + "\n", encoding="utf-8")
    return binary_path


def extract_video_frames(
    video_path: Path,
    output_dir: Path,
    *,
    sample_interval: float = 0.5,
    max_frames: int = 240,
    sampling_strategy: str = "adaptive",
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    engine = ocr_engine()
    binary = ensure_native_extractor() if engine in {"apple", "apple_vision", "vision", "native"} else None
    if sampling_strategy == "adaptive":
        from .sampling import adaptive_frames
        result = adaptive_frames(video_path, output_dir, sample_interval, max_frames)
        planned = result["frames"]
        manifest_path = output_dir / "ocr_manifest.json"
        manifest_path.write_text(json.dumps(planned, ensure_ascii=False), encoding="utf-8")
        if engine == "rapidocr":
            recognized = _recognize_manifest_rapidocr(planned)
            engine_label = "OpenCV adaptive decode + RapidOCR/ONNXRuntime"
        else:
            completed = subprocess.run([str(binary), "--ocr-manifest", str(manifest_path)],
                                       capture_output=True, text=True, timeout=900)
            if completed.returncode:
                raise VisionExtractionError(completed.stderr[-1800:])
            recognized = json.loads(completed.stdout)
            engine_label = "OpenCV adaptive decode + Apple Vision OCR"
        by_id = {f["frameId"]: f for f in planned}
        result["frames"] = [dict(by_id[f["frameId"]], **f) for f in recognized.get("frames", [])]
        result["errors"].extend(recognized.get("errors", []))
        if len(result["frames"]) != len(planned):
            result["sampling"]["sampling_complete"] = False
        result["engine"] = engine_label
        result["ocr_engine"] = recognized.get("provider_version", "") if engine == "rapidocr" else "Apple Vision/VNRecognizeTextRequest"
        return result
    if sampling_strategy != "uniform":
        raise ValueError("unknown sampling strategy")
    if engine == "rapidocr":
        # Production API uses adaptive sampling; uniform is retained for manual diagnostics.
        from .sampling import adaptive_frames
        result = adaptive_frames(video_path, output_dir, sample_interval, max_frames)
        recognized = _recognize_manifest_rapidocr(result["frames"])
        result["frames"] = recognized["frames"]
        result["errors"].extend(recognized["errors"])
        result["engine"] = "OpenCV decode + RapidOCR/ONNXRuntime (uniform request mapped to adaptive sampling)"
        result["ocr_engine"] = recognized["provider_version"]
        return result
    command = [
        str(binary),
        str(video_path),
        str(output_dir),
        f"{sample_interval:.3f}",
        str(max_frames),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if completed.returncode != 0:
        raise VisionExtractionError(
            "video extraction failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VisionExtractionError("native extractor returned invalid JSON") from exc
    if result.get("frames"):
        result["engine"] = "AVFoundation + Apple Vision"
        return result
    return _opencv_fallback(
        video_path,
        output_dir,
        binary=binary,
        sample_interval=sample_interval,
        max_frames=max_frames,
        native_result=result,
    )


def _opencv_fallback(
    video_path: Path,
    output_dir: Path,
    *,
    binary: Path,
    sample_interval: float,
    max_frames: int,
    native_result: dict,
) -> dict:
    """Use OpenCV for decoding and retain Apple Vision for OCR.

    Some screen-recording encoders cannot be decoded by AVAssetImageGenerator on
    a given host even though OpenCV can read them.  The fallback is explicit in
    the evidence manifest rather than silently changing providers.
    """

    try:
        import cv2
    except ImportError as exc:
        detail = "; ".join(str(item.get("message", "")) for item in native_result.get("errors", []))
        raise VisionExtractionError(
            f"AVFoundation could not decode the video ({detail}); install opencv-python-headless for fallback"
        ) from exc

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise VisionExtractionError("OpenCV fallback could not open the video")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    total_frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    duration = float(native_result.get("duration", 0.0))
    if duration <= 0 and fps > 0:
        duration = total_frames / fps
    manifest: list[dict] = []
    requested = 0.0
    index = 0
    try:
        while requested < duration and index < max_frames:
            capture.set(cv2.CAP_PROP_POS_MSEC, requested * 1000.0)
            ok, frame = capture.read()
            if ok and frame is not None:
                frame_id = f"frame_{index:06d}"
                image_path = (output_dir / f"{frame_id}.jpg").resolve()
                if cv2.imwrite(str(image_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88]):
                    actual_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC) or requested * 1000.0)
                    manifest.append({
                        "frameId": frame_id,
                        "timestamp": max(0.0, actual_ms / 1000.0),
                        "imagePath": str(image_path),
                    })
            requested += sample_interval
            index += 1
    finally:
        capture.release()
    if not manifest:
        raise VisionExtractionError("both AVFoundation and OpenCV failed to decode video frames")

    manifest_path = output_dir / "ocr_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [str(binary), "--ocr-manifest", str(manifest_path)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    if completed.returncode != 0:
        raise VisionExtractionError(
            "Apple Vision OCR fallback failed: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    try:
        recognized = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VisionExtractionError("Apple Vision OCR fallback returned invalid JSON") from exc
    return {
        "schemaVersion": "adsure-native-vision/v1",
        "duration": duration,
        "sampleInterval": sample_interval,
        "maxFrames": max_frames,
        "frames": recognized.get("frames", []),
        "errors": native_result.get("errors", []) + recognized.get("errors", []),
        "engine": "OpenCV decode fallback + Apple Vision OCR",
    }
