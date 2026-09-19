"""Private, allowlisted configuration. Never execute dotenv text or expose credentials."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit
from .env_config import load_env

NAMES = {"VIDEO_MVP_VLM_PROVIDER", "VIDEO_MVP_CLOUD_BASE_URL", "VIDEO_MVP_CLOUD_MODEL",
         "VIDEO_MVP_CLOUD_API_KEY", "VIDEO_MVP_CLOUD_CONSENT", "VIDEO_MVP_CLOUD_ALLOWED_VIDEO_SHA256"}


def values():
    return load_env(NAMES)


@dataclass(frozen=True)
class CloudConfig:
    provider: str
    endpoint: str
    model: str
    key: str = field(repr=False)
    consent: bool = False
    allowed_hashes: tuple[str, ...] = ()

    def authorized(self, video_sha256: str, consent_endpoint: str = "") -> bool:
        return bool(video_sha256 and (consent_endpoint == self.endpoint or
                    (self.consent and video_sha256 in self.allowed_hashes)))


def config() -> CloudConfig:
    data = values()
    endpoint = data.get("VIDEO_MVP_CLOUD_BASE_URL", "").rstrip("/")
    provider = data.get("VIDEO_MVP_VLM_PROVIDER", "local")
    if provider not in {"local", "cloud"}:
        raise ValueError("视觉 provider 只支持 local/cloud")
    if provider == "cloud":
        p = urlsplit(endpoint)
        if (p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment
                or any(c.isspace() for c in endpoint)):
            raise ValueError("云端 BASE_URL 必须为无凭据、无查询参数的 HTTPS API 根地址")
    model = data.get("VIDEO_MVP_CLOUD_MODEL", "")
    if not model and endpoint == "https://models.sjtu.edu.cn/api/v1":
        model = "qwen3.8-27b"
    if not model and urlsplit(endpoint).hostname and urlsplit(endpoint).hostname.endswith("volces.com"):
        # 火山方舟 Seed 2.1 Pro 稳定版多模态：适合证据级、结构化 JSON 观察。
        # evolving 版本能力可能更新，但周级变化不利于法务结果复现；
        # 可用 VIDEO_MVP_CLOUD_MODEL 覆盖为控制台中的具体模型/推理端点 ID。
        model = "doubao-seed-2-1-pro-260915"
    return CloudConfig(provider, endpoint, model, data.get("VIDEO_MVP_CLOUD_API_KEY", ""),
                       data.get("VIDEO_MVP_CLOUD_CONSENT") == "1",
                       tuple(data.get("VIDEO_MVP_CLOUD_ALLOWED_VIDEO_SHA256", "").split(",")))


def public_status():
    try:
        c = config()
        return {"provider": c.provider, "endpoint": c.endpoint, "model": c.model,
                "configured": bool(c.key and c.endpoint and c.model),
                "privacy": "每次任务明确授权后，仅发送最多12张代表帧及对应机器口播；完整视频、证明材料、活动规则和落地页文本不发送。"}
    except ValueError:
        return {"provider": "invalid", "configured": False, "error": "视觉配置格式无效"}
