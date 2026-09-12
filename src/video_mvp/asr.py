"""Local, timestamped audio transcription. No video/audio leaves the host."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .models import EvidenceUnit

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "data/video_mvp/models"


def model_path() -> Path:
    return Path(os.getenv("VIDEO_MVP_ASR_MODEL", str(MODEL_ROOT / "medium"))).resolve()


def readiness() -> dict:
    import importlib.util
    path = model_path()
    from .chinese_asr import readiness as chinese_readiness
    return {"provider": "faster-whisper", "model": str(path), "chinese": chinese_readiness(),
            "engine_policy": os.getenv("VIDEO_MVP_ASR_ENGINE", "dual"),
            "dependency_ready": importlib.util.find_spec("faster_whisper") is not None,
            "model_ready": all((path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json"))}


def model_provenance() -> dict:
    from importlib.metadata import version, PackageNotFoundError
    try:
        identity = json.loads((model_path() / "adsure_model_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        identity = {"status": "model_manifest_missing"}
    try:
        identity["provider_version"] = version("faster-whisper")
    except PackageNotFoundError:
        identity["provider_version"] = "not_installed"
    return identity


def transcribe_video(video: Path, output: Path) -> tuple[list[EvidenceUnit], dict]:
    """Isolate native inference so a hung decoder/model cannot hang a job forever."""
    raw_path = output / "asr_raw.json"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "src.video_mvp.asr", "--video", str(video), "--output", str(raw_path)],
            cwd=ROOT, capture_output=True, text=True,
            timeout=int(os.getenv("VIDEO_MVP_ASR_TIMEOUT", "900")),
        )
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-1800:])
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
    except Exception as exc:
        payload = {"status": "failed", "error": str(exc), "segments": [], "provider": "faster-whisper"}
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    units = [EvidenceUnit(
        id=f"audio_{i:06d}", source="asr", kind="text", text=s["text"],
        t_start=s["start"], t_end=s["end"], confidence=s.get("confidence"),
        provider=payload.get("provider", "faster-whisper"), provider_version=payload.get("model", ""),
        raw_ref={"path": "asr_raw.json", "segment_index": i, "audio_track": s["audio_track"],
                 "words": s.get("words", []), "time_basis": "decoded_audio"},
    ) for i, s in enumerate(payload.get("segments", []))]
    verification = payload.get("verification", {})
    units.extend(EvidenceUnit(
        id=f"audio_alt_{i:06d}",source="asr",kind="text",text=s["text"],
        t_start=s["start"],t_end=s["end"],confidence=s.get("confidence"),
        provider=verification.get("provider",""),provider_version=verification.get("model",""),
        raw_ref={"path":"asr_raw.json","branch":"verification","segment_index":i,
                 "audio_track":s["audio_track"],"words":s.get("words",[]),"time_basis":"decoded_audio",
                 "verification_status":"independent_machine_hypothesis"})
        for i,s in enumerate(verification.get("segments",[])))
    status = {k: v for k, v in payload.items() if k != "segments"}
    status["segment_count"] = len(units)
    return units, status


def run_worker(video: Path) -> dict:
    from .chinese_asr import readiness as chinese_readiness, run_worker as chinese_worker, compare_transcripts
    engine = os.getenv("VIDEO_MVP_ASR_ENGINE", "dual")
    if engine not in {"dual", "sensevoice", "whisper"}:
        raise ValueError("VIDEO_MVP_ASR_ENGINE must be dual, sensevoice, or whisper")
    ready = chinese_readiness()
    if engine == "whisper" or not (ready["dependency_ready"] and ready["model_ready"]):
        result = _whisper_worker(video)
        if engine != "whisper":
            result["fallback_reason"] = "中文专用模型未就绪，回退 Whisper；未完成双引擎核验"
        return result
    if engine == "sensevoice":
        return chinese_worker(video)
    primary = _whisper_worker(video)
    if engine == "dual":
        try:
            verification = chinese_worker(video)
            primary["verification"] = verification
            primary["engine_disagreements"] = compare_transcripts(primary["segments"], verification["segments"])
            primary["engine_disagreements"].extend({**d,"primary":d["alternative"],"alternative":d["primary"]}
                for d in compare_transcripts(verification["segments"],primary["segments"]) if not d["alternative"])
            primary["quality_status"] = "engines_disagree" if primary["engine_disagreements"] else "cross_checked_unverified"
            if verification["status"] in {"failed","partial","no_speech_detected"}:
                primary["quality_status"] = "verification_failed"
            if not primary["segments"] and verification.get("segments"):
                primary["status"] = "partial"
        except Exception as exc:
            primary["verification"] = {"status":"failed", "error":str(exc)}
            primary["quality_status"] = "verification_failed"
    return primary


def _whisper_worker(video: Path) -> dict:
    import av
    import numpy as np
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    with av.open(str(video)) as container:
        tracks = [s for s in container.streams if s.type == "audio"]
        track_info = [{"index": s.index, "offset": float(s.start_time * s.time_base) if s.start_time else 0.0}
                      for s in tracks]
    payload = {"status": "no_audio_track", "provider": "faster-whisper", "model": str(model_path()),
               "model_provenance": model_provenance(),
               "audio_tracks": len(track_info), "segments": [], "track_results": []}
    if not track_info:
        return payload
    if not readiness()["model_ready"]:
        raise RuntimeError("本地 ASR 模型未安装。运行 .venv-video/bin/python -m src.video_mvp.asr --download-model medium")
    model = WhisperModel(str(model_path()), device="cpu", compute_type="int8",
                         cpu_threads=int(os.getenv("VIDEO_MVP_ASR_THREADS", "4")), local_files_only=True)
    # Each audio stream is remuxed locally, avoiding silently ignoring secondary narration tracks.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="adsure-audio-") as temporary:
        for info in track_info:
            audio_path = Path(temporary) / f"track-{info['index']}.mka"
            try:
                with av.open(str(video)) as source, av.open(str(audio_path), "w", format="matroska") as target:
                    stream = source.streams[info["index"]]
                    out = target.add_stream_from_template(stream)
                    for packet in source.demux(stream):
                        if packet.dts is None:
                            continue
                        packet.stream = out
                        target.mux(packet)
                audio = decode_audio(str(audio_path), sampling_rate=16000)
                duration = len(audio) / 16000
                if not len(audio):
                    raise RuntimeError("音轨解码为空")
                # Digital silence is distinct from a recognition failure or music-only audio.
                if float(np.max(np.abs(audio))) < 1e-5:
                    payload["track_results"].append({"track": info["index"], "status": "silent", "duration": duration})
                    continue
                segments, metadata = model.transcribe(
                    audio, language="zh", beam_size=5, word_timestamps=True,
                    vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
                    condition_on_previous_text=False,
                )
                count = 0
                for segment in segments:
                    if not segment.text.strip():
                        continue
                    words = [{"word": w.word, "start": max(0., w.start + info["offset"]),
                              "end": max(0., w.end + info["offset"]), "probability": w.probability}
                             for w in segment.words or []]
                    payload["segments"].append({"text": segment.text.strip(), "audio_track": info["index"],
                        "start": max(0., segment.start + info["offset"]), "end": max(0., segment.end + info["offset"]),
                        "confidence": sum(w["probability"] for w in words) / len(words) if words else None,
                        "avg_logprob": segment.avg_logprob, "no_speech_prob": segment.no_speech_prob, "words": words})
                    count += 1
                payload["track_results"].append({"track": info["index"], "status": "transcribed" if count else "no_speech_detected",
                                                "duration": duration, "language_probability": metadata.language_probability})
            except Exception as exc:
                payload["track_results"].append({"track": info["index"], "status": "failed", "error": str(exc)})
    states = {s["status"] for s in payload["track_results"]}
    payload["status"] = ("partial" if payload["segments"] else "failed") if "failed" in states else (
        "transcribed" if payload["segments"] else "silent" if states == {"silent"} else "no_speech_detected")
    payload["low_confidence_segments"] = [
        {"start": s["start"], "end": s["end"], "confidence": s["confidence"]}
        for s in payload["segments"] if s["confidence"] is None or s["confidence"] < .6
    ]
    payload["quality_status"] = "needs_listening_review" if payload["low_confidence_segments"] else "machine_transcribed_unverified"
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-model", choices=["tiny", "base", "small", "medium", "large-v3"])
    parser.add_argument("--video", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.download_model:
        from huggingface_hub import snapshot_download
        destination = MODEL_ROOT / args.download_model
        snapshot_download(f"Systran/faster-whisper-{args.download_model}", local_dir=destination,
                          allow_patterns=["*.json", "model.bin", "vocabulary.*", "README.md"], token=False)
        digest = hashlib.sha256()
        with (destination / "model.bin").open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        (destination / "adsure_model_manifest.json").write_text(json.dumps({
            "repo": f"Systran/faster-whisper-{args.download_model}", "model_sha256": digest.hexdigest()
        }, indent=2), encoding="utf-8")
        print(destination)
    elif args.video and args.output:
        args.output.write_text(json.dumps(run_worker(args.video), ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        parser.error("provide --download-model or --video and --output")


if __name__ == "__main__":
    main()
