"""Allowlisted private configuration loader for video MVP run modes.

The file is plain ``KEY=value`` text and is never executed. Process
environment variables always override file values, making one-off local
experiments explicit and auditable.
"""
from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def env_path() -> Path:
    """Return the explicitly selected video env file.

    Defaults to ``.env.video.volc.example`` for this Volcano workflow per the
    current operational request. For production/private use, set
    ``VIDEO_MVP_ENV_FILE=.env.video.volc.local``.
    """
    raw = os.getenv("VIDEO_MVP_ENV_FILE", ".env.video.volc.example")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_env(allowed_names: set[str]) -> dict[str, str]:
    path = env_path()
    result: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, separator, value = line.partition("=")
            name = name.strip()
            if separator and name in allowed_names:
                result[name] = value.strip().strip("\"'")
    result.update({name: os.environ[name] for name in allowed_names if name in os.environ})
    return result


def env_source() -> dict[str, str | bool]:
    path = env_path()
    return {"path": str(path), "exists": path.is_file()}
