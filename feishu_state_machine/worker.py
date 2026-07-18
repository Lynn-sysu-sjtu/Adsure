"""
飞书多维表格轮询触发器

每 N 秒扫一次表，捕获新提交记录（状态为空且物料内容非空），
向提交人发送互动卡片，等运营点击「开启 AI 审核」按钮后触发审核链路。
"""
import os
import time
import json
import requests

from config import BITABLE_APP_TOKEN, BITABLE_TABLE_ID
from feishu_api import get_tenant_access_token, list_all_records, update_record, download_attachment, upload_image
from fields_v4 import (
    F_物料编号, F_物料内容, F_物料附件, F_行业领域, F_提交人, F_紧急程度,
    F_流转_当前状态,
    F_美妆_投放平台, F_游戏_投放平台, F_保健食品_投放平台,
)

_PLATFORM_FIELD = {
    "美妆":   F_美妆_投放平台,
    "游戏":   F_游戏_投放平台,
    "保健食品": F_保健食品_投放平台,
}

# === 配置 ===
POLL_INTERVAL = 5
WORKBENCH_URL = "http://localhost:5001/"


# === 工具函数 ===

def _text_of(raw):
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in raw)
    if isinstance(raw, dict):
        return raw.get("text") or raw.get("name") or ""
    return str(raw)


def _open_id_of(raw):
    """从飞书 User 字段取 open_id（人员字段=list，创建人字段=dict）"""
    if isinstance(raw, list) and raw:
        return raw[0].get("id") or raw[0].get("open_id")
    if isinstance(raw, dict):
        return raw.get("id") or raw.get("open_id")
    return None


def _user_name(raw):
    if isinstance(raw, list) and raw:
        return raw[0].get("name") or raw[0].get("en_name") or "未知"
    if isinstance(raw, dict):
        return raw.get("name") or raw.get("en_name") or "未知"
    return "未知"


# === 发送互动卡片 ===

def send_review_card(record_id, fields):
    """向提交人发送带「开启 AI 审核」按钮的互动卡片"""
    open_id = _open_id_of(fields.get(F_提交人))
    if not open_id:
        print("    ⚠ 提交人 open_id 为空，跳过卡片发送（手动在多维表格触发）")
        return

    industry  = fields.get(F_行业领域, "未填")
    submitter = _user_name(fields.get(F_提交人))
    content   = _text_of(fields.get(F_物料内容))
    urgency   = fields.get(F_紧急程度, "普通")

    # 判断是图片物料还是文字物料
    attachments = fields.get(F_物料附件) or []
    if isinstance(attachments, dict):
        attachments = [attachments]
    image_att = next((a for a in attachments if isinstance(a, dict) and a.get("file_token")), None)
    is_image_material = bool(image_att) and not content.strip()

    # 尝试上传图片拿 img_key（失败则降级为文字提示）
    img_key = None
    if is_image_material and image_att:
        try:
            img_bytes = download_attachment(image_att["file_token"])
            img_key = upload_image(img_bytes)
        except Exception as e:
            print(f"    ⚠ 图片上传失败，降级为文字提示: {e}")

    preview = content[:100] + ("…" if len(content) > 100 else "") if content.strip() else None
    platform  = _text_of(fields.get(_PLATFORM_FIELD.get(industry, ""), "")) or "未填"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 物料已提交 · {urgency}"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**行业领域**\n{industry}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**提交人**\n{submitter}"}},
                ],
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**投放平台**\n{platform}"},
            },
            # 物料预览：图片显示缩略图，文字显示前100字
            *([
                {"tag": "div", "text": {"tag": "lark_md", "content": "**物料预览**"}},
                {
                    "tag": "img",
                    "img_key": img_key,
                    "alt": {"tag": "plain_text", "content": "物料图片"},
                    "mode": "crop_center",
                },
            ] if img_key else [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**物料预览**\n{preview or '（图片物料，AI审核时自动识别）'}"},
            }]),
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "请确认内容无误后，选择是否启用 AI 审核"}],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🚀 开启 AI 审核"},
                        "type": "primary",
                        "value": {"action": "start_ai_review", "record_id": record_id},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✏️ 修改物料"},
                        "type": "default",
                        "url": f"https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb?table=tblL8R7yL1rCeU7m&view=vewMSBI3s8&record={record_id}",
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "跳过 → 直发法务"},
                        "type": "default",
                        "value": {"action": "skip_review", "record_id": record_id},
                    },
                ],
            },
        ],
    }

    try:
        token = get_tenant_access_token()
        r = requests.post(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "receive_id": open_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
            timeout=5,
        ).json()
        if r.get("code") == 0:
            print(f"    ✓ 互动卡片已发送给运营（open_id={open_id[:12]}…）")
        else:
            print(f"    ✗ 卡片发送失败 code={r.get('code')} msg={r.get('msg','')[:80]}")
    except Exception as e:
        print(f"    ✗ 卡片发送异常: {e}")


# === 核心逻辑 ===

def is_new_submission(fields):
    """状态为空 + (物料内容非空 或 有图片附件) = 新提交"""
    status  = fields.get(F_流转_当前状态, "")
    content = _text_of(fields.get(F_物料内容))
    has_attachment = bool(fields.get(F_物料附件))
    return (not status) and (bool(content.strip()) or has_attachment)


def process_record(record_id, fields):
    code = str(fields.get(F_物料编号, "")) or "(待编号)"
    print(f"  ★ 捕获新提交 record_id={record_id}  物料编号={code}")

    # 1. 先把状态推进到「运营起草」，防止下一次轮询重复处理
    try:
        update_record(record_id, {F_流转_当前状态: "运营起草"})
        print(f"    ✓ 状态 → 运营起草")
    except Exception as e:
        print(f"    ✗ 状态更新失败: {e}")
        return  # 状态没更新成功就不发卡片，下次轮询会重试

    # 2. 向提交人发互动卡片
    send_review_card(record_id, fields)


def poll_once():
    try:
        records  = list_all_records()
        new_ones = [
            (r["record_id"], r.get("fields", {}))
            for r in records
            if is_new_submission(r.get("fields", {}))
        ]
        if new_ones:
            print(f"[{time.strftime('%H:%M:%S')}] 扫描 {len(records)} 条，发现 {len(new_ones)} 条新提交")
            for rid, fields in new_ones:
                process_record(rid, fields)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] 轮询异常: {e}")


def main():
    print("=" * 60)
    print("审心 · 多维表格轮询触发器启动")
    print(f"  表: {BITABLE_APP_TOKEN}/{BITABLE_TABLE_ID}")
    print(f"  间隔: {POLL_INTERVAL}s")
    print(f"  触发条件: ⑤流转·当前状态=空 且 ①运营·物料内容!=空")
    print(f"  触发动作: 状态→运营起草 + 给提交人发互动卡片")
    print("=" * 60)
    while True:
        poll_once()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
