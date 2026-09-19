"""Private, allowlisted configuration. Never execute dotenv text or expose credentials."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit

PRIVATE_ENV = Path(__file__).resolve().parents[2] / ".env.video.local"
NAMES = {"VIDEO_MVP_VLM_PROVIDER", "VIDEO_MVP_CLOUD_BASE_URL", "VIDEO_MVP_CLOUD_MODEL",
         "VIDEO_MVP_CLOUD_API_KEY", "VIDEO_MVP_CLOUD_CONSENT", "VIDEO_MVP_CLOUD_ALLOWED_VIDEO_SHA256"}


def values():
    result = {}
    if PRIVATE_ENV.is_file():
        for line in PRIVATE_ENV.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() in NAMES:
                result[name.strip()] = value.strip().strip('\"\'')
    result.update({name: os.environ[name] for name in NAMES if name in os.environ})
    return result


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
