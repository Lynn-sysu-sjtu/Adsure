from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from .models import EvidenceUnit

PATTERN_PATH = Path(__file__).resolve().parents[2] / "data/rules/video_claim_patterns.json"


@lru_cache(maxsize=1)
def _converter():
    try:
        from opencc import OpenCC
        return OpenCC("t2s")
    except ImportError:
        return None


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    converter = _converter()
    if converter:
        text = converter.convert(text)
    return re.sub(r"[\s\u200b\ufeff\u200c\u200d]+", "", text)


def compact(text: str) -> str:
    return re.sub(r"[，。！？、；：,.!?;:‘’“”\"'（）()【】\[\]—-]", "", normalize(text))


def catalog() -> dict:
    return json.loads(PATTERN_PATH.read_text(encoding="utf-8"))


def negated(text: str, start: int, end: int) -> bool:
    """Only a directly governing negation suppresses a match, never the whole ad."""
    left = text[:start]
    clause = re.split(r"[，。！？；,!?;]", left)[-1][-16:]
    if clause.endswith("还不是"):
        return False  # rhetorical assertion: “还不是…”, not a disclaimer
    return bool(re.search(r"(?:不能|不可|不得|不应|无法|并非|不是|不具备|不具有|没有|不保证|不承诺|不宣称|不)(?:代替药物|用于|具有|有|进行|做到|能够|能)?$", clause))


def _close(a: EvidenceUnit, b: EvidenceUnit) -> bool:
    if a.source == "asr":
        return (a.provider == b.provider and a.raw_ref.get("audio_track") == b.raw_ref.get("audio_track")
                and -.05 <= b.t_start - a.t_end <= .6)
    if a.frame_ids != b.frame_ids or not a.bbox or not b.bbox:
        return False
    x, y, w, h = a.bbox
    bx, by, bw, bh = b.bbox
    return (abs(by-y) < max(h,bh)*.6 and 0 <= bx-(x+w) < .04) or (
        abs(bx-x) < .08 and -.01 <= by-(y+h) <= max(.04,h))


def text_windows(evidence: list[EvidenceUnit]) -> list[EvidenceUnit]:
    """Keep originals and bounded windows, with reversible original-ID references."""
    result = list(evidence)
    groups = defaultdict(list)
    for item in evidence:
        groups[(item.source, tuple(item.frame_ids) if item.source == "ocr" else (item.provider, item.raw_ref.get("audio_track")))].append(item)
    for group in groups.values():
        group.sort(key=lambda e: (e.t_start, round((e.bbox or [0, 0])[1], 2), (e.bbox or [0])[0]))
        for i in range(len(group)-1):
            items = [group[i]]
            for following in group[i+1:i+3]:
                if not _close(items[-1], following):
                    break
                items.append(following)
                if sum(len(s.text) for s in items) > 240 or following.t_end - items[0].t_start > 20:
                    break
                # Raw line/segment boundaries remain inspectable in constituent IDs.
                boxes = [s.bbox for s in items if s.bbox]
                box = None
                if len(boxes) == len(items):
                    x = min(b[0] for b in boxes); y = min(b[1] for b in boxes)
                    box = [x, y, max(b[0]+b[2] for b in boxes)-x, max(b[1]+b[3] for b in boxes)-y]
                result.append(replace(items[0], id="window:"+":".join(s.id for s in items),
                    text="".join(s.text for s in items), t_end=items[-1].t_end, bbox=box,
                    raw_ref={"constituent_ids": [s.id for s in items], "method": "adjacent_window",
                             "parts": [s.text for s in items]}))
    return result
