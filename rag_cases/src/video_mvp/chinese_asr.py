"""Local Chinese SenseVoice branch, retained separately from Whisper hypotheses."""
from __future__ import annotations

import json
import os
import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from .setup_models import SENSE_DIR
from .textmatch import compact


def readiness():
    import importlib.util
    return {"provider": "sherpa-onnx/SenseVoice", "model": str(SENSE_DIR),
            "dependency_ready": importlib.util.find_spec("sherpa_onnx") is not None,
            "model_ready": all((SENSE_DIR / n).is_file() for n in ["model.int8.onnx", "tokens.txt", "manifest.json"])}


def compare_transcripts(primary: list[dict], secondary: list[dict]) -> list[dict]:
    differences = []
    for segment in primary:
        overlaps = [s for s in secondary if s["audio_track"] == segment["audio_track"] and
                    min(s["end"], segment["end"]) > max(s["start"], segment["start"]) + .05]
        # Compare only temporally corresponding words, not an entire 20-second
        # secondary chunk against one short Whisper sentence.
        alternative = "".join("".join(w["word"] for w in s["words"]
                    if min(w["end"],segment["end"]) > max(w["start"],segment["start"])+.01)
                    if s.get("words") else s["text"] for s in overlaps)
        # Disagreement is a review signal, never authority to rewrite either engine.
        similarity = SequenceMatcher(None, compact(segment["text"]), compact(alternative)).ratio()
        numbers_differ = re.findall(r"\d+(?:\.\d+)?%?",compact(segment["text"])) != re.findall(r"\d+(?:\.\d+)?%?",compact(alternative))
        if not overlaps or similarity < .90 or numbers_differ:
            differences.append({"start":segment["start"], "end":segment["end"], "audio_track":segment["audio_track"],
                                "primary":segment["text"], "alternative":alternative, "agreement":round(similarity,3),
                                "comparison_threshold":.90,"numbers_differ":numbers_differ})
    return differences


def run_worker(video: Path) -> dict:
    import av
    import numpy as np
    import sherpa_onnx
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import get_speech_timestamps, VadOptions
    from importlib.metadata import version

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(SENSE_DIR / "model.int8.onnx"), tokens=str(SENSE_DIR / "tokens.txt"),
        num_threads=int(os.getenv("VIDEO_MVP_ASR_THREADS", "4")), use_itn=True, language="zh", debug=False)
    payload = {"status":"no_audio_track", "provider":"sherpa-onnx/SenseVoice", "model":str(SENSE_DIR),
               "model_provenance":{**json.loads((SENSE_DIR / "manifest.json").read_text()),"provider_version":version("sherpa-onnx")},
               "segments":[], "track_results":[], "low_confidence_segments":[], "quality_status":"machine_transcribed_unverified"}
    with av.open(str(video)) as source:
        tracks = [{"index":s.index,"offset":float(s.start_time * s.time_base) if s.start_time else 0.}
                  for s in source.streams if s.type == "audio"]
    payload["audio_tracks"] = len(tracks)
    with tempfile.TemporaryDirectory(prefix="adsure-chinese-asr-") as tmp:
        for track in tracks:
            try:
                path = Path(tmp) / f"track-{track['index']}.mka"
                with av.open(str(video)) as source, av.open(str(path), "w", format="matroska") as target:
                    stream = source.streams[track["index"]]
                    out = target.add_stream_from_template(stream)
                    for packet in source.demux(stream):
                        if packet.dts is not None:
                            packet.stream = out
                            target.mux(packet)
                audio = decode_audio(str(path), sampling_rate=16000)
                if not len(audio):
                    raise ValueError("音轨为空")
                if float(np.max(np.abs(audio))) < 1e-5:
                    payload["track_results"].append({"track":track["index"],"status":"silent"})
                    continue
                speech_regions = get_speech_timestamps(audio, VadOptions(threshold=.3, min_silence_duration_ms=350, max_speech_duration_s=20, speech_pad_ms=150))
                # VAD is a quality hint only: noisy/quiet narration must not be discarded.
                # Decode the whole track in bounded windows with context on both sides.
                regions = [{"core_start":start,"core_end":min(start+20*16000,len(audio)),
                            "start":max(0,start-5600),"end":min(start+20*16000+5600,len(audio))}
                           for start in range(0,len(audio),20*16000)]
                before = len(payload["segments"])
                for region in regions:
                    start, end = region["start"], region["end"]
                    offset = start / 16000 + track["offset"]
                    stream = recognizer.create_stream()
                    stream.accept_waveform(16000, audio[start:end])
                    recognizer.decode_stream(stream)
                    result = stream.result
                    words = []
                    tokens, timestamps = list(result.tokens), list(result.timestamps)
                    for i, (token, timestamp) in enumerate(zip(tokens, timestamps)):
                        token = re.sub(r"<\|.*?\|>", "", token).replace("▁", " ")
                        if not token.strip():
                            continue
                        stop = timestamps[i+1] if i+1 < len(timestamps) else min(timestamp+.2,(end-start)/16000)
                        words.append({"word":token,"start":max(0.,offset+timestamp),"end":max(0.,offset+stop),"probability":None})
                    selected_words = [w for w in words if region["core_start"]/16000+track["offset"] <= (w["start"]+w["end"])/2 < region["core_end"]/16000+track["offset"]]
                    if not selected_words and not result.text.strip():
                        continue
                    if not selected_words:
                        selected_words=words
                    # Retain decoder text even if token rendering/ITN differs.
                    payload["segments"].append({"text":"".join(w["word"] for w in selected_words).strip() or re.sub(r"<\|.*?\|>","",result.text).strip(),
                        "decoder_text_with_context":result.text,
                        "start":max(0.,selected_words[0]["start"] if selected_words else offset),
                        "end":max(0.,selected_words[-1]["end"] if selected_words else offset+(end-start)/16000),
                        "audio_track":track["index"],"confidence":None,"confidence_basis":"not_exposed_by_ctc",
                        "words":selected_words,"decode_region":{"start":offset,"end":offset+(end-start)/16000}})
                payload["track_results"].append({"track":track["index"],"status":"transcribed" if len(payload["segments"]) > before else "no_speech_detected","duration":len(audio)/16000,
                                                "decode_coverage":"full_track_windows","vad_detected_regions":len(speech_regions)})
            except Exception as exc:
                payload["track_results"].append({"track":track["index"],"status":"failed","error":str(exc)})
    states = {r["status"] for r in payload["track_results"]}
    if tracks:
        payload["status"] = ("partial" if payload["segments"] else "failed") if "failed" in states else (
            "transcribed" if payload["segments"] else "silent" if states == {"silent"} else "no_speech_detected")
    return payload
