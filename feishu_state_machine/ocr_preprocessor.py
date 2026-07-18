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

from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.ocr.v20181119 import ocr_client, models

from config import TENCENT_SECRET_ID, TENCENT_SECRET_KEY, TENCENT_OCR_REGION
from feishu_api import download_attachment, update_record
from fields_v4 import F_物料附件, F_物料内容

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
    cred = credential.Credential(TENCENT_SECRET_ID, TENCENT_SECRET_KEY)
    client = ocr_client.OcrClient(cred, TENCENT_OCR_REGION)

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
        print(f"[ocr] record_id={record_id} 附件中无图片，跳过")
        return ""

    print(f"[ocr] record_id={record_id} 发现 {len(images)} 张图片，开始 OCR")

    parts = []
    for idx, att in enumerate(images, 1):
        file_token = att.get("file_token")
        name = att.get("name", f"图片{idx}")
        if not file_token:
            print(f"[ocr]   跳过第{idx}张：无 file_token")
            continue
        try:
            print(f"[ocr]   第{idx}张：{name}")
            image_bytes = download_attachment(file_token)
            text = _ocr_image(image_bytes)
            if text.strip():
                parts.append(text.strip())
                print(f"[ocr]   ✓ 提取到 {len(text)} 字")
            else:
                print(f"[ocr]   图片中无文字")
        except TencentCloudSDKException as e:
            print(f"[ocr]   ✗ 腾讯云 OCR 失败: {e}")
        except Exception as e:
            print(f"[ocr]   ✗ 第{idx}张处理失败: {e}")

    if not parts:
        return ""

    combined = "\n\n".join(parts)

    try:
        update_record(record_id, {F_物料内容: combined})
        print(f"[ocr] ✓ OCR 结果已写回「物料内容」，共 {len(combined)} 字")
    except Exception as e:
        print(f"[ocr] ✗ 写回失败（非致命）: {e}")

    return combined
