"""
OCR 预处理模块 — 腾讯云通用印刷体识别

当飞书记录的「物料内容」为空但「物料附件」有图片时：
  下载图片 → 腾讯云 OCR → 提取文案 → 写回「物料内容」字段

调用入口（供 predictor.build_context 使用）：
    from ocr_preprocessor import extract_text_from_attachments
    text = extract_text_from_attachments(record_id, fields)

设计原则：
- 失败不阻断主流程：OCR 报错只打印日志，返回 ""
- 写回飞书：成功后自动写入「物料内容」，避免重复 OCR
- 仅处理图片附件，跳过 PDF/Word 等
"""

import base64
import logging

from feishu_api import download_attachment, update_record
from fields_v4 import F_物料附件, F_物料内容
from logging_utils import context_fields

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
SUPPORTED_MIME_TYPES = {
    "image/jpeg", "image/jpg", "image/png",
    "image/gif", "image/webp", "image/bmp",
}


def _is_image(attachment: dict) -> bool:
    mime = (attachment.get("type") or "").lower()
    name = (attachment.get("name") or "").lower()
    return mime in SUPPORTED_MIME_TYPES or any(name.endswith(e) for e in SUPPORTED_EXTENSIONS)


def _ocr_image(image_bytes: bytes) -> str:
    """调用腾讯云通用印刷体识别，返回拼接后的文本。"""
    try:
        import config
        from tencentcloud.common import credential
        from tencentcloud.ocr.v20181119 import ocr_client, models
        secret_id = getattr(config, "TENCENT_SECRET_ID", "")
        secret_key = getattr(config, "TENCENT_SECRET_KEY", "")
        region = getattr(config, "TENCENT_OCR_REGION", "ap-guangzhou")
        if not secret_id or not secret_key:
            raise RuntimeError("attachment text provider is not configured")
    except ImportError as exc:
        raise RuntimeError("attachment text provider is unavailable") from exc

    cred = credential.Credential(secret_id, secret_key)
    client = ocr_client.OcrClient(cred, region)

    req = models.GeneralBasicOCRRequest()
    req.ImageBase64 = base64.b64encode(image_bytes).decode("utf-8")

    resp = client.GeneralBasicOCR(req)
    lines = [item.DetectedText for item in (resp.TextDetections or [])]
    return "\n".join(lines)


def extract_text_from_attachments(record_id: str, fields: dict) -> str:
    """
    从附件字段提取图片文案。

    - 若「物料内容」已有文字，直接返回（不重复 OCR）
    - 遍历「物料附件」中所有图片，逐张 OCR，拼接结果
    - 成功后写回「物料内容」字段
    - 任何步骤失败只打印日志，不抛异常
    """
    # 已有文字内容，跳过
    existing = fields.get(F_物料内容)
    if existing:
        if isinstance(existing, str) and existing.strip():
            return existing.strip()
        if isinstance(existing, list) and existing:
            text = "".join(
                seg.get("text", "") if isinstance(seg, dict) else str(seg)
                for seg in existing
            ).strip()
            if text:
                return text

    raw = fields.get(F_物料附件)
    if not raw:
        return ""

    attachments = raw if isinstance(raw, list) else [raw]
    images = [a for a in attachments if isinstance(a, dict) and _is_image(a)]

    if not images:
        logger.info(
            "event=attachment_text_skipped %s",
            context_fields(record_id=record_id, reason="no_images"),
        )
        return ""

    logger.info(
        "event=attachment_text_started %s",
        context_fields(record_id=record_id, image_count=len(images)),
    )

    parts = []
    for idx, att in enumerate(images, 1):
        file_token = att.get("file_token")
        if not file_token:
            logger.warning(
                "event=attachment_missing_token %s",
                context_fields(record_id=record_id, index=idx),
            )
            continue
        try:
            logger.info(
                "event=attachment_text_image_started %s",
                context_fields(record_id=record_id, index=idx),
            )
            image_bytes = download_attachment(file_token)
            text = _ocr_image(image_bytes)
            if text.strip():
                parts.append(text.strip())
                logger.info(
                    "event=attachment_text_image_completed %s",
                    context_fields(
                        record_id=record_id, index=idx, text_length=len(text)
                    ),
                )
            else:
                logger.info(
                    "event=attachment_text_image_empty %s",
                    context_fields(record_id=record_id, index=idx),
                )
        except Exception:
            logger.warning(
                "event=attachment_text_image_failed %s error_category=attachment_processing",
                context_fields(record_id=record_id, index=idx),
            )

    if not parts:
        return ""

    combined = "\n\n".join(parts)

    # 写回飞书，最多重试 2 次——规则引擎会直接读飞书字段，写回失败则审核无法继续
    last_err = None
    for attempt in range(1, 3):
        try:
            update_record(record_id, {F_物料内容: combined})
            logger.info(
                "event=attachment_text_writeback_completed %s",
                context_fields(record_id=record_id, text_length=len(combined)),
            )
            last_err = None
            break
        except Exception as exc:
            last_err = exc
            logger.warning(
                "event=attachment_text_writeback_failed %s "
                "error_category=transient_network",
                context_fields(record_id=record_id, attempt=attempt),
            )

    if last_err:
        raise RuntimeError("attachment text writeback failed") from last_err

    return combined
