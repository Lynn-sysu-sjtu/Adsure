"""
飞书长连接监听器 — 接收卡片按钮回调，驱动两步审核流程

流程：
  1. 运营点「开启AI审核」→ 上下文重建 → 发「模式确认卡片」
  2. 运营点某个模式按钮  → 正式调用规则引擎 + LLM

运行方式：python3 bot_listener.py
依赖：pip3 install lark-oapi
"""
import json
import threading
import requests
from typing import Optional

import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
    CallBackToast,
)

import feishu_api
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, WORKBENCH_URL, LEGAL_DEPT_NAME
from fields_v4 import F_流转_当前状态, F_物料内容, F_预审_风险等级, F_预审_命中要点


def _trim(text: str, max_len: int = 80) -> str:
    """命中要点截断：只取第一句（分号前），超长截断。"""
    if not text:
        return text
    for sep in ['；', '\n', ';']:
        idx = text.find(sep)
        if idx > 0:
            return text[:idx].strip()
    return text[:max_len].strip() + ("…" if len(text) > max_len else "")


# ===== 卡片按钮回调 =====

def handle_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    resp = P2CardActionTriggerResponse()
    try:
        value       = (data.event.action.value or {}) if data.event and data.event.action else {}
        action      = value.get("action", "")
        record_id   = value.get("record_id", "")
        operator_id = data.event.operator.open_id if data.event and data.event.operator else None
        print(f"[bot_listener] 回调 action={action!r} record_id={record_id!r}")

        # ── 运营修改完毕，重新发起审核 ───────────────────────────
        if action == "resubmit" and record_id:
            threading.Thread(
                target=_run_resubmit,
                args=(record_id, operator_id),
                daemon=True,
            ).start()
            toast = CallBackToast()
            toast.type    = "success"
            toast.content = "已收到，正在准备重新提交…"
            resp.toast = toast
            return resp

        # ── 步骤一：运营点「开启AI审核」→ 直接以标准模式开始审核 ─────
        if action == "start_ai_review" and record_id:
            # 防重：已在 AI预审中 则忽略，避免运营重复点击发出多次请求
            try:
                rec = feishu_api.get_record(record_id)
                current_status = rec.get("fields", {}).get(F_流转_当前状态, "")
                if current_status == "AI预审中":
                    toast = CallBackToast()
                    toast.type    = "info"
                    toast.content = "AI审核正在进行中，请勿重复点击"
                    resp.toast = toast
                    return resp
            except Exception as e:
                print(f"[bot_listener] 防重检查异常: {e}")

            threading.Thread(
                target=_run_execute,
                args=(record_id, "标准", operator_id),
                daemon=True,
            ).start()
            toast = CallBackToast()
            toast.type    = "success"
            toast.content = "AI 审核已开始，完成后将通知您…"
            resp.toast = toast
            return resp

        # ── 跳过 AI，直发法务 ─────────────────────────────────────
        if action == "skip_review" and record_id:
            feishu_api.update_record(record_id, {F_流转_当前状态: "待法务复核"})
            toast = CallBackToast()
            toast.type    = "info"
            toast.content = "已跳过预审，直接转法务"
            resp.toast = toast
            return resp

        # ── 运营将 AI 结果直接升级转法务 ────────────────────────────
        if action == "escalate_to_legal" and record_id:
            threading.Thread(
                target=_run_escalate,
                args=(record_id,),
                daemon=True,
            ).start()
            toast = CallBackToast()
            toast.type    = "info"
            toast.content = "已转交法务，等待复核…"
            resp.toast = toast
            return resp

    except Exception as e:
        print(f"[bot_listener] 回调处理异常: {e}")

    return resp


# ===== 后台线程 =====

def _run_prepare(record_id: str, operator_open_id: Optional[str]):
    """步骤一：上下文重建 + 发模式确认卡片"""
    try:
        feishu_api.update_record(record_id, {F_流转_当前状态: "AI预审中"})
        from predictor import prepare
        ctx, recommended_mode = prepare(record_id)
        _send_mode_card(record_id, ctx, recommended_mode, operator_open_id)
    except Exception as e:
        print(f"[bot_listener] prepare 异常: {e}")
        _on_audit_error(record_id, operator_open_id, str(e))


def _run_execute(record_id: str, mode: str, operator_open_id: Optional[str]):
    """正式审核（规则引擎 + LLM + 回写），完成后按路由发通知"""
    try:
        feishu_api.update_record(record_id, {F_流转_当前状态: "AI预审中"})
        from predictor import execute
        routing, llm_result = execute(record_id, mode)

        if routing == "待运营修改":
            _notify_operator_result(record_id, llm_result, operator_open_id)
        elif routing == "待法务复核":
            _notify_legal(record_id, llm_result)
            _notify_operator_transferred(record_id, llm_result, operator_open_id)
    except Exception as e:
        print(f"[bot_listener] execute 异常: {e}")
        _on_audit_error(record_id, operator_open_id, str(e))


def _run_resubmit(record_id: str, operator_open_id: Optional[str]):
    """运营修改完毕：重置状态 + 重新发一张三按钮卡片"""
    try:
        # 重置到运营起草（不置空，避免 worker.py 重复检测）
        feishu_api.update_record(record_id, {F_流转_当前状态: "运营起草"})

        # 取最新记录数据，重建卡片
        rec    = feishu_api.get_record(record_id)
        fields = rec.get("fields", {})

        from worker import send_review_card
        send_review_card(record_id, fields)
        print(f"[bot_listener] ✓ 重新提交卡片已发送 record_id={record_id}")
    except Exception as e:
        print(f"[bot_listener] resubmit 异常: {e}")


def _run_escalate(record_id: str):
    """运营将 AI 审核结果直接升级转法务：更新状态 + 通知法务"""
    try:
        feishu_api.update_record(record_id, {F_流转_当前状态: "待法务复核"})

        # 读取已有的 AI 审核结果（预审段字段）
        rec = feishu_api.get_record(record_id)
        fields = rec.get("fields", {})
        llm_result = {
            "预审_风险等级": fields.get(F_预审_风险等级, "未知"),
            "预审_命中要点": fields.get(F_预审_命中要点, "（无）"),
        }
        _notify_legal(record_id, llm_result)
        print(f"[bot_listener] ✓ 运营主动升级转法务 record_id={record_id}")
    except Exception as e:
        print(f"[bot_listener] escalate 异常: {e}")


# ===== 审核结果通知 =====

def _on_audit_error(record_id: str, open_id: Optional[str], err_msg: str):
    """
    审核流程异常统一处理：
    1. 状态回退到「运营起草」，让运营可以重新点「开启AI审核」
    2. 若有 open_id，向运营推送失败通知卡片
    """
    try:
        feishu_api.update_record(record_id, {F_流转_当前状态: "运营起草"})
        print(f"[bot_listener] 审核失败，状态已回退为「运营起草」record_id={record_id}")
    except Exception as e:
        print(f"[bot_listener] 状态回退失败: {e}")

    if not open_id:
        return

    # 截断错误信息，避免卡片内容过长
    display_err = err_msg[:120] + "…" if len(err_msg) > 120 else err_msg

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⚠️ AI审核失败，请重新提交"},
            "template": "red",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md",
                "content": f"**失败原因**\n{display_err}"}},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text",
                "content": "物料状态已回退为「运营起草」，你可以重新点击「开启AI审核」再次尝试"}]},
        ],
    }
    _send_card_to(open_id, card)
    print(f"[bot_listener] 审核失败通知已推送给运营 record_id={record_id}")


def _notify_operator_result(record_id: str, llm_result: dict, open_id: Optional[str]):
    """路由→运营自改：向运营推送审核结果卡片"""
    if not open_id:
        print("[bot_listener] ⚠ 运营 open_id 为空，无法发送结果通知")
        return

    risk     = llm_result.get("预审_风险等级", "未知")
    points   = _trim(llm_result.get("预审_命中要点", "（无）"))
    suggest  = llm_result.get("预审_修改建议", "（无）")
    bitable_url = (
        f"https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb"
        f"?table=tblL8R7yL1rCeU7m&view=vewMSBI3s8&record={record_id}"
    )
    kanban_url = (
        f"https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb"
        f"?table=tblL8R7yL1rCeU7m&view=vewEddfI3c&record={record_id}"
    )
    risk_color = {"高": "red", "中": "orange", "低": "green"}.get(risk, "blue")

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"⚠️ AI审核完成 · 风险等级：{risk}"},
            "template": risk_color,
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**命中要点**\n{points}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**修改建议**\n{suggest}"}},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text",
                "content": "请根据以上建议修改物料，修改完成后点击「重新提交」"}]},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                 "type": "default", "url": kanban_url},
                {"tag": "button", "text": {"tag": "plain_text", "content": "✏️ 去修改物料"},
                 "type": "default", "url": bitable_url},
                {"tag": "button", "text": {"tag": "plain_text", "content": "✅ 修改完成，重新提交"},
                 "type": "primary",
                 "value": {"action": "resubmit", "record_id": record_id}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "⚖️ 转交法务复核"},
                 "type": "default",
                 "value": {"action": "escalate_to_legal", "record_id": record_id}},
            ]},
        ],
    }
    _send_card_to(open_id, card)
    print(f"[bot_listener] ✓ 审核结果已推送给运营（routing=待运营修改）")


def _notify_legal(record_id: str, llm_result: dict):
    """路由→法务复核：向「法务部」所有成员发飞书通知"""
    try:
        legal_ids = feishu_api.get_dept_open_ids(LEGAL_DEPT_NAME)
    except Exception as e:
        print(f"[bot_listener] ⚠ 查询法务部成员失败: {e}")
        return

    if not legal_ids:
        print(f"[bot_listener] ⚠ 「{LEGAL_DEPT_NAME}」暂无成员，通知未发送")
        return

    risk   = llm_result.get("预审_风险等级", "未知")
    points = _trim(llm_result.get("预审_命中要点", "（无）"))

    # 取物料内容原文做预览
    try:
        rec = feishu_api.get_record(record_id)
        raw_content = rec.get("fields", {}).get(F_物料内容, "")
        # 飞书富文本字段可能是列表，展平为纯文本
        if isinstance(raw_content, list):
            raw_content = "".join(
                seg.get("text", "") if isinstance(seg, dict) else str(seg)
                for seg in raw_content
            )
        content_preview = (raw_content[:50] + "…") if len(raw_content) > 50 else raw_content or f"#{record_id[-8:]}"
    except Exception:
        content_preview = f"#{record_id[-8:]}"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📨 新物料待法务复核"},
            "template": "orange",
        },
        "elements": [
            {"tag": "div", "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**风险等级**\n{risk}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**物料内容**\n{content_preview}"}},
            ]},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**AI命中要点**\n{points}"}},
            {"tag": "hr"},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "🖥 打开法务工作台"},
                 "type": "primary", "url": WORKBENCH_URL},
            ]},
        ],
    }

    for oid in legal_ids:
        _send_card_to(oid, card)
    print(f"[bot_listener] ✓ 法务通知已发送给 {len(legal_ids)} 名法务成员")


def _notify_operator_transferred(record_id: str, llm_result: dict, open_id: Optional[str]):
    """路由→法务复核时，告知运营物料已流转到法务，等待法务裁决。"""
    if not open_id:
        print("[bot_listener] ⚠ 运营 open_id 为空，无法发送流转通知")
        return

    risk   = llm_result.get("预审_风险等级", "未知")
    points = _trim(llm_result.get("预审_命中要点", "（无）"))
    bitable_url = (
        f"https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb"
        f"?table=tblL8R7yL1rCeU7m&view=vewMSBI3s8&record={record_id}"
    )
    kanban_url = (
        f"https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb"
        f"?table=tblL8R7yL1rCeU7m&view=vewEddfI3c&record={record_id}"
    )

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⏳ 物料已流转至法务，等待裁决"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**AI风险等级**\n{risk}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": "**当前状态**\n待法务复核"}},
            ]},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**AI命中要点**\n{points}"}},
            {"tag": "hr"},
            {"tag": "note", "elements": [{"tag": "plain_text",
                "content": "AI审核完成，因存在需法律解释的风险点，已自动转交法务团队复核。法务裁决后你将收到通知。"}]},
            {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                 "type": "primary", "url": kanban_url},
                {"tag": "button", "text": {"tag": "plain_text", "content": "📋 查看物料详情"},
                 "type": "default", "url": bitable_url},
            ]},
        ],
    }
    _send_card_to(open_id, card)
    print(f"[bot_listener] ✓ 流转通知已推送给运营 record_id={record_id}")


def _send_card_to(open_id: str, card: dict):
    """向指定 open_id 发送互动卡片（委托给 feishu_api）"""
    feishu_api.send_card_to(open_id, card)


# ===== 模式确认卡片 =====

def _send_mode_card(record_id: str, ctx: dict, recommended_mode: str, open_id: Optional[str]):
    """向运营发送模式确认卡片"""
    if not open_id:
        print("[bot_listener] ⚠ operator open_id 为空，无法发送模式确认卡片")
        return

    content_preview = ctx["content"][:80] + ("…" if len(ctx["content"]) > 80 else "")

    def _btn(label: str, mode: str):
        is_recommended = (mode == recommended_mode)
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": f"{label}{'  ★推荐' if is_recommended else ''}"},
            "type": "primary" if is_recommended else "default",
            "value": {"action": "confirm_mode", "record_id": record_id, "mode": mode},
        }

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🔍 上下文分析完成，请确认审核模式"},
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**行业领域**\n{ctx['industry'] or '未填'}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**紧急程度**\n{ctx['urgency']}"}},
                ],
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**物料预览**\n{content_preview}"},
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": (
                    "**审核模式说明**\n"
                    "⚡ **极速** · 快速识别违禁词和明显违规\n"
                    "✅ **标准** · 综合合规审核（推荐日常使用）\n"
                    "🔬 **深度** · 逐条比对法律条款，适合高风险物料"
                )},
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": f"AI 推荐【{recommended_mode}】模式，你也可以切换后点击确认"}],
            },
            {
                "tag": "action",
                "actions": [
                    _btn("⚡ 极速", "极速"),
                    _btn("✅ 标准", "标准"),
                    _btn("🔬 深度", "深度"),
                ],
            },
        ],
    }

    _send_card_to(open_id, card)
    print(f"[bot_listener] ✓ 模式确认卡片已发送")


# ===== 启动长连接 =====

def main():
    print("=" * 50)
    print("审心 · 飞书长连接监听器启动")
    print(f"  App ID : {FEISHU_APP_ID}")
    print("  监听   : card.action.trigger")
    print("=" * 50)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(handle_card_action)
        .build()
    )

    ws_client = lark.ws.Client(
        app_id=FEISHU_APP_ID,
        app_secret=FEISHU_APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    ws_client.start()


if __name__ == "__main__":
    main()
