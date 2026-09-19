from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NATIVE_SOURCE = Path(__file__).with_name("native_vision.m")
DEFAULT_BINARY = PROJECT_ROOT / "tmp" / "video_mvp" / "adsure_vision"


class VisionExtractionError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    binary = ensure_native_extractor()
    output_dir.mkdir(parents=True, exist_ok=True)
    if sampling_strategy == "adaptive":
        from .sampling import adaptive_frames
        result = adaptive_frames(video_path, output_dir, sample_interval, max_frames)
        planned = result["frames"]
        manifest_path = output_dir / "ocr_manifest.json"
        manifest_path.write_text(json.dumps(planned, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run([str(binary), "--ocr-manifest", str(manifest_path)],
                                   capture_output=True, text=True, timeout=900)
        if completed.returncode:
            raise VisionExtractionError(completed.stderr[-1800:])
        recognized = json.loads(completed.stdout)
        by_id = {f["frameId"]: f for f in planned}
        result["frames"] = [dict(by_id[f["frameId"]], **f) for f in recognized.get("frames", [])]
        result["errors"].extend(recognized.get("errors", []))
        if len(result["frames"]) != len(planned):
            result["sampling"]["sampling_complete"] = False
        result["engine"] = "OpenCV adaptive decode + Apple Vision OCR"
        return result
    if sampling_strategy != "uniform":
        raise ValueError("unknown sampling strategy")
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
