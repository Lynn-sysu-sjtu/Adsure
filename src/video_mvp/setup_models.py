"""Explicit model download; review jobs never download or send material externally."""
import hashlib
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENSE_DIR = ROOT / "data/video_mvp/models/sensevoice"
SENSE_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09.tar.bz2"


def download_sensevoice():
    SENSE_DIR.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(SENSE_DIR).free < 1024**3 + 350 * 1024**2:
        raise RuntimeError("磁盘不足：下载后必须保留至少 1 GiB 可用空间")
    hashes = {}
    with urllib.request.urlopen(SENSE_URL, timeout=120) as response, tarfile.open(fileobj=response, mode="r|bz2") as archive:
        for member in archive:
            name = Path(member.name).name
            if name not in {"model.int8.onnx", "tokens.txt"} or not member.isfile():
                continue
            if name in hashes or member.size > 300 * 1024**2:
                raise ValueError("unexpected model archive")
            path = SENSE_DIR / name
            temporary = path.with_suffix(path.suffix + ".partial")
            digest = hashlib.sha256()
            with archive.extractfile(member) as source, temporary.open("wb") as target:
                while block := source.read(1024**2):
                    digest.update(block)
                    target.write(block)
            temporary.replace(path)
            hashes[name] = digest.hexdigest()
    if set(hashes) != {"model.int8.onnx", "tokens.txt"}:
        raise ValueError("incomplete model archive")
    (SENSE_DIR / "manifest.json").write_text(json.dumps({"source_url": SENSE_URL, "sha256": hashes}, indent=2))
    print(SENSE_DIR)


if __name__ == "__main__":
    download_sensevoice()
