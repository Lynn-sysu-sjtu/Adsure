"""Two-pass sampling: regular coverage plus local visual changes and tail frames."""
from __future__ import annotations

import math
from pathlib import Path


def select_candidates(candidates: list[dict], max_frames: int) -> tuple[list[dict], int]:
    ordered = sorted(candidates, key=lambda c: c["timestamp"])
    if len(ordered) <= max_frames:
        return ordered, 0
    # Retain baseline across the entire duration before allocating change frames.
    base = [c for c in ordered if "baseline" in c["reasons"] or "tail" in c["reasons"]]
    if len(base) > max_frames:
        indices = [round(i * (len(base) - 1) / (max_frames - 1)) for i in range(max_frames)] if max_frames > 1 else [0]
        selected = [base[i] for i in indices]
    else:
        base_ids = {c["index"] for c in base}
        remaining = [c for c in ordered if c["index"] not in base_ids]
        remaining.sort(key=lambda c: c["change_score"], reverse=True)
        selected = base + remaining[:max_frames - len(base)]
    return sorted(selected, key=lambda c: c["timestamp"]), len(ordered) - len(selected)


def adaptive_frames(video: Path, output_dir: Path, interval: float, max_frames: int) -> dict:
    import cv2
    import numpy as np
    if not math.isfinite(interval) or interval <= 0 or max_frames < 1:
        raise ValueError("抽帧参数无效")
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError("无法打开视频")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not math.isfinite(fps) or fps <= 0:
        raise RuntimeError("无法确定视频帧率")
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps
    if duration > 1800:
        capture.release()
        raise ValueError("当前单任务上限为 30 分钟，请分段审核")
    # 100ms probes inspect local text changes as well as whole-shot changes.
    probe_step = min(.1, interval)
    next_probe = 0.
    next_base = 0.
    previous = None
    previous_record = None
    candidates: dict[int, dict] = {}
    probes = 0
    decoded = 0

    def add(record: dict, reason: str):
        found = candidates.setdefault(record["index"], dict(record, reasons=[]))
        if reason not in found["reasons"]:
            found["reasons"].append(reason)

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            index = decoded
            decoded += 1
            timestamp = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000
            if not math.isfinite(timestamp) or timestamp <= 0 and index:
                timestamp = index / fps
            tail = index == total - 1
            if timestamp + 1e-6 < next_probe and not tail:
                continue
            probes += 1
            next_probe = timestamp + probe_step - .5 / fps
            small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (192, 108)).astype(np.float32)
            score = 0.
            if previous is not None:
                diff = np.abs(small - previous) / 255.
                # Max tile mean catches small overlay changes missed by global mean.
                tile_means = diff.reshape(6, 18, 8, 24).mean(axis=(1, 3))
                score = max(float(diff.mean()), float(tile_means.max()))
            record = {"index": index, "timestamp": timestamp, "change_score": round(score, 5)}
            if timestamp + .5 / fps >= next_base:
                add(record, "baseline")
                next_base = timestamp + interval
            if score >= .09:
                if previous_record:
                    add(previous_record, "before_change")
                add(record, "visual_change")
            if tail:
                add(record, "tail")
            previous, previous_record = small, record
    finally:
        capture.release()
    if previous_record:
        add(previous_record, "tail")
    selected, omitted = select_candidates(list(candidates.values()), max_frames)
    selected_by_index = {c["index"]: c for c in selected}
    frames = []
    errors = []
    output_dir.mkdir(parents=True, exist_ok=True)
    # Sequential second decode avoids seeking to the wrong keyframe.
    capture = cv2.VideoCapture(str(video))
    try:
        for index in range(decoded):
            ok, frame = capture.read()
            if not ok:
                errors.append({"stage": "extract_frame", "message": "二次解码提前结束", "index": index})
                break
            if index not in selected_by_index:
                continue
            record = selected_by_index[index]
            frame_id = f"frame_{index:08d}"
            path = (output_dir / (frame_id + ".jpg")).resolve()
            if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                errors.append({"stage": "save_frame", "index": index})
                continue
            frames.append({"frameId": frame_id, "imagePath": str(path), "timestamp": record["timestamp"],
                           "reasons": record["reasons"], "change_score": record["change_score"]})
    finally:
        capture.release()
    times = [0.] + [f["timestamp"] for f in frames] + [duration]
    gap = max((b - a for a, b in zip(times, times[1:])), default=duration)
    return {"duration": duration, "frames": frames, "errors": errors, "sampling": {
        "strategy": "baseline+local_change+before_change+tail/v2", "interval": interval,
        "probe_interval": probe_step, "probe_count": probes, "candidate_count": len(candidates),
        "omitted_candidates": omitted, "decoded_frames": decoded, "expected_decoded_frames": total,
        "max_gap_seconds": gap, "decode_complete": decoded >= total and total > 0,
        "sampling_complete": total > 0 and bool(frames) and omitted == 0 and not errors and decoded >= total and len(frames) == len(selected),
        "limitation": "抽样不能保证捕获短于探测间隔的文字；未实现逐帧语义审核。"}}
