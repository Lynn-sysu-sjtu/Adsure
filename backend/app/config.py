"""全局配置。

所有密钥只从环境变量读取，用 SecretStr 包住，避免误打印到日志。
Provider 开关集中在这里 —— 这是方案里「商用留口」的落地处：
今天没 GPU 走云 API，将来换 FunASR / PaddleOCR / Tarsier2，只改 env 不改业务代码。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent


class PipelineSettings(BaseSettings):
    """取证层参数。

    ⚠️ 这里的默认值是**基于公开经验的起始值，不是标定值**。
    阶段 0.4 拿到真实广告素材后必须重新标定，标定结果回写到这里并记录依据。
    """

    model_config = SettingsConfigDict(env_prefix="PIPELINE_", extra="ignore")

    # ── 抽帧策略：场景关键帧 ∪ 固定采样 ──────────────────────
    # 不能只用场景关键帧：广告花字的典型形态是「同一镜头内文字不断变化」，
    # 场景没切但文字全换了，只抽关键帧会大面积漏检。
    sample_fps: float = 2.0

    # PySceneDetect ContentDetector 阈值。官方默认 27.0。
    # 广告剪辑快、转场花哨，可能需要下调才不欠分割 —— 待真实素材标定。
    scene_threshold: float = 27.0

    # ── pHash 去重 ───────────────────────────────────────────
    # 汉明距离阈值：≤ 该值视为重复帧。64 位 pHash 上 5 是常见起点。
    # 调大 → 省 OCR 钱但可能吃掉「文字变了背景没变」的帧（漏检）；
    # 调小 → 召回稳但成本上去。这个权衡必须用真实素材实测，别拍脑袋。
    phash_hamming_threshold: int = 5
    phash_size: int = 8  # 8 → 64 位指纹

    # ── 字幕跨帧合并（merge.py）──────────────────────────────
    # 合并条件是「文本相似度 AND 空间 IoU」双条件。
    # 只看文本会把画面上下两处同时出现的不同花字错误合并成一条。
    merge_text_similarity: float = 0.85  # rapidfuzz ratio，0-1
    merge_bbox_iou: float = 0.30
    merge_max_gap_seconds: float = 0.8  # 超过这个间隔即使内容相同也断开

    # ── 口播分段（违禁词匹配用）──────────────────────────────
    # ASR 切出的「句子」是识别产物不是语义边界，违禁词会横跨两句
    # （「……本品是国家」+「级配方……」），所以同一段连续语流必须拼起来整体匹配。
    #
    # 但「连续」要有限度：相隔十几秒的两句话拼在一起，会让报告里的
    # 上下文出现现实中根本没有连着说过的句子——而上下文是给法务做判断的证据。
    # 超过这个间隔就视为两段独立语流，各自建索引。
    asr_join_max_gap_seconds: float = 1.0

    # ── 显著性判定（L4 必备要素核查用）──────────────────────
    # 「写了但只闪 0.5 秒 / 字号只占画面 2% / 藏在角落」= 未显著标明。
    # ⚠️ 这三个阈值是**产品判断，不是法律标准**。法律上"显著"没有统一量化标准，
    #    这里只作为「提请人工复核」的触发线，报告措辞不得表述为已构成违法。
    salience_min_duration: float = 1.0  # 秒
    salience_min_font_scale: float = 0.025  # 文字高度 / 画面高度
    salience_edge_margin: float = 0.08  # 距画面边缘小于此比例视为「角落」

    # ── 成本红线（硬限制，超了直接抛错，不静默截断）──────────
    max_ocr_calls_per_video: int = 20
    max_vlm_calls_per_video: int = 4
    max_video_duration_seconds: int = 300
    max_video_size_mb: int = 500


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 两处都读：项目根的 .env 是既有约定（与本仓库其他部分共用，
        # 变量带 LEX_ 前缀），backend/.env 是本模块自己的。
        # 后者优先，便于本模块单独覆盖。
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "adsure-video-review"
    debug: bool = False

    # ── Provider 开关 ────────────────────────────────────────
    asr_provider: Literal["aliyun", "tencent", "volcengine", "funasr_local"] = "aliyun"
    ocr_provider: Literal["aliyun", "tencent", "baidu", "paddle_local"] = "aliyun"
    vlm_provider: Literal["volcengine", "qwen", "zhipu", "tarsier_local",
                          "openai_compat", "mock"] = "volcengine"
    llm_provider: Literal["mock", "deepseek", "volcengine"] = "mock"

    # ── ASR ──────────────────────────────────────────────────
    asr_access_key_id: str = ""
    asr_access_key_secret: SecretStr = SecretStr("")
    asr_app_key: str = ""
    asr_region: str = "cn-shanghai"
    asr_endpoint: str = ""

    # ── ASR · 火山 Seed-ASR（asr_provider=volcengine 时使用）────────
    # 兼容旧 MVP 的 VIDEO_MVP_VOLC_SPEECH_* 命名，一份凭据两边可用。
    asr_volc_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "ASR_VOLC_API_KEY", "VIDEO_MVP_VOLC_SPEECH_API_KEY",
            "VIDEO_MVP_VOLC_SPEECH_ACCESS_KEY",
        ),
    )
    asr_volc_resource_id: str = Field(
        default="volc.seedasr.auc",
        validation_alias=AliasChoices(
            "ASR_VOLC_RESOURCE_ID", "VIDEO_MVP_VOLC_SPEECH_RESOURCE_ID"),
    )
    asr_volc_base_url: str = Field(
        default="https://openspeech.bytedance.com",
        validation_alias=AliasChoices(
            "ASR_VOLC_BASE_URL", "VIDEO_MVP_VOLC_SPEECH_BASE_URL"),
    )
    asr_volc_api_path: str = Field(
        default="/api/v3/auc/bigmodel",
        validation_alias=AliasChoices(
            "ASR_VOLC_API_PATH", "VIDEO_MVP_VOLC_SPEECH_API_PATH"),
    )
    asr_volc_model: str = Field(
        default="bigmodel",
        validation_alias=AliasChoices(
            "ASR_VOLC_MODEL", "VIDEO_MVP_VOLC_SPEECH_MODEL"),
    )
    asr_volc_uid: str = Field(
        default="adsure",
        validation_alias=AliasChoices(
            "ASR_VOLC_UID", "VIDEO_MVP_VOLC_SPEECH_UID"),
    )

    # ── OCR ──────────────────────────────────────────────────
    ocr_access_key_id: str = ""
    ocr_access_key_secret: SecretStr = SecretStr("")
    ocr_region: str = "cn-shanghai"
    ocr_endpoint: str = ""

    # ── VLM / LLM ────────────────────────────────────────────
    # 兼容旧 MVP 的 VIDEO_MVP_CLOUD_* 命名，一份凭据两边可用。
    vlm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "VLM_API_KEY", "VIDEO_MVP_CLOUD_API_KEY"),
    )
    vlm_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "VLM_ENDPOINT", "VIDEO_MVP_CLOUD_BASE_URL"),
    )
    vlm_model: str = Field(
        default="",
        validation_alias=AliasChoices(
            "VLM_MODEL", "VIDEO_MVP_CLOUD_MODEL"),
    )
    # 兼容既有 .env 的 LEX_DEEPSEEK_* 命名 —— 迁就现有约定，
    # 而不是要求改一份别的地方也在用的配置文件。
    llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("LLM_API_KEY", "LEX_DEEPSEEK_API_KEY"),
    )
    llm_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_ENDPOINT", "LEX_DEEPSEEK_BASE_URL"),
    )
    llm_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("LLM_MODEL", "LEX_DEEPSEEK_MODEL"),
    )

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key.get_secret_value())

    # ── 存储 ─────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://adsure:adsure@localhost:5432/adsure"
    redis_url: str = "redis://localhost:6379/0"
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: SecretStr = SecretStr("")

    # ── 飞书 ─────────────────────────────────────────────────
    feishu_app_id: str = ""
    feishu_app_secret: SecretStr = SecretStr("")
    feishu_verification_token: str = ""
    feishu_encrypt_key: SecretStr = SecretStr("")
    feishu_bitable_app_token: str = ""
    feishu_bitable_table_id: str = ""
    web_base_url: str = "http://localhost:5173"

    # ── 审心现有服务（留空则降级到 mock）────────────────────
    adsure_rule_engine_url: str = ""
    adsure_case_lib_url: str = ""
    adsure_internal_token: SecretStr = SecretStr("")

    # ── 外部工具 ─────────────────────────────────────────────
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    # ── 工作目录 ─────────────────────────────────────────────
    work_dir: Path = Field(default=PROJECT_ROOT / "var" / "work")

    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)

    @property
    def rule_engine_available(self) -> bool:
        """审心规则引擎是否可用。不可用时 recall.py 降级到本地词库 + mock，不阻塞主链路。"""
        return bool(self.adsure_rule_engine_url)

    @property
    def case_lib_available(self) -> bool:
        return bool(self.adsure_case_lib_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
