"""Existing Adsure cards, rebuilt from persisted record state at delivery time."""

from __future__ import annotations

from typing import Any, Optional

from fields_v4 import (
    F_物料编号,
    F_行业领域,
    F_物料内容,
    F_物料附件,
    F_提交人,
    F_紧急程度,
    F_美妆_投放平台,
    F_游戏_投放平台,
    F_保健食品_投放平台,
    F_预审_风险等级,
    F_预审_命中要点,
    F_预审_修改建议,
    F_法务_AI意见评价,
    F_法务_物料裁决,
    F_法务_最终修改意见,
)
from user_messages import FINAL_FAILURE_BODY, FINAL_FAILURE_BUTTON, FINAL_FAILURE_TITLE


_BASE = "https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb"
_PLATFORM_FIELD = {
    "美妆": F_美妆_投放平台,
    "游戏": F_游戏_投放平台,
    "保健食品": F_保健食品_投放平台,
}


def _text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(
            (
                str(item.get("text") or item.get("name") or "")
                if isinstance(item, dict)
                else str(item)
            )
            for item in raw
        )
    if isinstance(raw, dict):
        return str(raw.get("text") or raw.get("name") or "")
    return str(raw)


def _open_id(raw: Any) -> Optional[str]:
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        value = raw.get("id") or raw.get("open_id")
        return str(value) if value else None
    return None


def _user_name(raw: Any) -> str:
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("en_name") or "未知")
    return "未知"


def _md(value: Any) -> str:
    """Render untrusted values as literal text inside Feishu markdown blocks."""
    text = _text(value)
    for char in ("\\", "*", "_", "~", "[", "]", "(", ")", "`", ">"):
        text = text.replace(char, "\\" + char)
    return text


def _urls(record_id: str) -> tuple[str, str]:
    detail = f"{_BASE}?table=tblL8R7yL1rCeU7m&view=vewMSBI3s8&record={record_id}"
    kanban = f"{_BASE}?table=tblL8R7yL1rCeU7m&view=vewEddfI3c&record={record_id}"
    return detail, kanban


def submitter_open_id(fields: dict) -> Optional[str]:
    return _open_id(fields.get(F_提交人))


def build_initial_review_card(
    record_id: str,
    fields: dict,
    *,
    image_key: Optional[str] = None,
    round_number: Optional[int] = None,
) -> dict:
    industry = _text(fields.get(F_行业领域)) or "未填"
    submitter = _user_name(fields.get(F_提交人))
    content = _text(fields.get(F_物料内容))
    urgency = _text(fields.get(F_紧急程度)) or "普通"
    platform = _text(fields.get(_PLATFORM_FIELD.get(industry, ""))) or "未填"
    preview = (
        content[:100] + ("…" if len(content) > 100 else "") if content.strip() else None
    )
    detail_url, _ = _urls(record_id)
    preview_elements = (
        [
            {"tag": "div", "text": {"tag": "lark_md", "content": "**物料预览**"}},
            {
                "tag": "img",
                "img_key": image_key,
                "alt": {"tag": "plain_text", "content": "物料图片"},
                "mode": "crop_center",
            },
        ]
        if image_key
        else [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**物料预览**\n{_md(preview or '（图片物料，AI审核时自动识别）')}",
                },
            }
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 物料已提交 · {urgency}"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**行业领域**\n{_md(industry)}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**提交人**\n{_md(submitter)}",
                        },
                    },
                ],
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**投放平台**\n{_md(platform)}"},
            },
            *preview_elements,
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "请确认内容无误后，选择是否启用 AI 审核",
                    }
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🚀 开启 AI 审核"},
                        "type": "primary",
                        "value": _action_value(
                            "start_ai_review", record_id, round_number
                        ),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✏️ 修改物料"},
                        "type": "default",
                        "url": detail_url,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "跳过 → 直发法务"},
                        "type": "default",
                        "value": _action_value("skip_review", record_id, round_number),
                    },
                ],
            },
        ],
    }


def build_context_confirm_card(
    record_id: str,
    fields: dict,
    *,
    round_number: Optional[int] = None,
    image_key: Optional[str] = None,
) -> dict:
    industry = _text(fields.get(F_行业领域)) or "未填"
    urgency = _text(fields.get(F_紧急程度)) or "普通"
    content = _text(fields.get(F_物料内容))
    preview = (
        content[:100] + ("…" if len(content) > 100 else "") if content.strip() else None
    )
    preview_elements = (
        [
            {"tag": "div", "text": {"tag": "lark_md", "content": "**物料预览**"}},
            {
                "tag": "img",
                "img_key": image_key,
                "alt": {"tag": "plain_text", "content": "物料图片"},
                "mode": "crop_center",
            },
        ]
        if image_key
        else [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**物料预览**\n{_md(preview or '（图片物料，AI审核时自动识别）')}",
                },
            }
        ]
    )

    def _mode_value(mode: str) -> dict:
        value = {"action": "confirm_mode", "record_id": record_id, "mode": mode}
        if round_number is not None:
            value["round"] = int(round_number)
        return value

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🔍 上下文分析完成，请确认审核模式",
            },
            "template": "green",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**行业领域**\n{_md(industry)}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**紧急程度**\n{_md(urgency)}",
                        },
                    },
                ],
            },
            *preview_elements,
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**审核模式说明**\n"
                        "⚡ 极速 · 快速识别违禁词和明显违规\n"
                        "✅ 标准 · 综合合规审核（推荐日常使用）\n"
                        "🔬 深度 · 逐条比对法律条款，适合高风险物料"
                    ),
                },
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "AI 推荐【标准】模式，你也可以切换后点击确认",
                    }
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "⚡ 极速"},
                        "type": "default",
                        "value": _mode_value("极速"),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 标准 ★推荐"},
                        "type": "primary",
                        "value": _mode_value("标准"),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🔬 深度"},
                        "type": "default",
                        "value": _mode_value("深度"),
                    },
                ],
            },
        ],
    }


def build_operator_result_card(
    record_id: str, fields: dict, *, round_number: Optional[int] = None
) -> dict:
    risk = _text(fields.get(F_预审_风险等级)) or "未知"
    points = _short(fields.get(F_预审_命中要点), 80)
    suggestion = _text(fields.get(F_预审_修改建议)) or "（无）"
    detail_url, kanban_url = _urls(record_id)
    color = {"高": "red", "中": "orange", "低": "green"}.get(risk, "blue")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"⚠️ AI审核完成 · 风险等级：{risk}",
            },
            "template": color,
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**命中要点**\n{_md(points or '（无）')}",
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**修改建议**\n{_md(suggestion)}",
                },
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "请根据以上建议修改物料，修改完成后点击「重新提交」",
                    }
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                        "type": "default",
                        "url": kanban_url,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✏️ 去修改物料"},
                        "type": "default",
                        "url": detail_url,
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ 修改完成，重新提交",
                        },
                        "type": "primary",
                        "value": _action_value("resubmit", record_id, round_number),
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "⚖️ 转交法务复核"},
                        "type": "default",
                        "value": _action_value(
                            "escalate_to_legal", record_id, round_number
                        ),
                    },
                ],
            },
        ],
    }


def build_more_info_card(
    record_id: str, fields: dict, *, round_number: Optional[int] = None
) -> dict:
    detail_url, kanban_url = _urls(record_id)
    points = _short(fields.get(F_预审_命中要点), 100) or "请补充物料相关信息"
    suggestion = _text(fields.get(F_预审_修改建议))
    elements = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**需要补充**\n{_md(points)}"},
        },
    ]
    if suggestion:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**补充建议**\n{_md(suggestion)}",
                },
            }
        )
    elements.extend(
        [
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✏️ 去补充"},
                        "type": "primary",
                        "url": detail_url,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                        "type": "default",
                        "url": kanban_url,
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": "✅ 补充完成，重新提交",
                        },
                        "type": "default",
                        "value": _action_value("resubmit", record_id, round_number),
                    },
                ],
            },
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📝 请补充物料信息"},
            "template": "orange",
        },
        "elements": elements,
    }


def build_legal_review_card(
    record_id: str, fields: dict, *, workbench_url: str
) -> dict:
    risk = _text(fields.get(F_预审_风险等级)) or "未知"
    points = _short(fields.get(F_预审_命中要点), 80) or "（无）"
    content = _text(fields.get(F_物料内容))
    preview = (
        content[:50] + ("…" if len(content) > 50 else "")
        if content
        else f"#{record_id[-8:]}"
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📨 新物料待法务复核"},
            "template": "orange",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**风险等级**\n{_md(risk)}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**物料内容**\n{_md(preview)}",
                        },
                    },
                ],
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**AI命中要点**\n{_md(points)}"},
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🖥 打开法务工作台"},
                        "type": "primary",
                        "url": workbench_url,
                    }
                ],
            },
        ],
    }


def build_operator_transferred_card(record_id: str, fields: dict) -> dict:
    risk = _text(fields.get(F_预审_风险等级)) or "未知"
    points = _short(fields.get(F_预审_命中要点), 80) or "（无）"
    detail_url, kanban_url = _urls(record_id)
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⏳ 物料已流转至法务，等待裁决"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**AI风险等级**\n{_md(risk)}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": "**当前状态**\n待法务复核",
                        },
                    },
                ],
            },
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**AI命中要点**\n{_md(points)}"},
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "审核已完成并转交法务团队复核。法务裁决后你将收到通知。",
                    }
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                        "type": "primary",
                        "url": kanban_url,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📋 查看物料详情"},
                        "type": "default",
                        "url": detail_url,
                    },
                ],
            },
        ],
    }


def build_verdict_card(
    record_id: str, fields: dict, *, round_number: Optional[int] = None
) -> dict:
    ai_opinion = _text(fields.get(F_法务_AI意见评价))
    verdict = _text(fields.get(F_法务_物料裁决))
    final_suggestion = _text(fields.get(F_法务_最终修改意见))
    serial = _text(fields.get(F_物料编号)) or record_id[-6:]
    content = _text(fields.get(F_物料内容))
    preview = content[:60] + ("…" if len(content) > 60 else "")
    passed = verdict == "通过"
    detail_url, kanban_url = _urls(record_id)
    elements = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**物料内容**\n{_md(preview)}"},
        }
    ]
    if not passed and final_suggestion:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**修改意见**\n{_md(final_suggestion)}",
                },
            }
        )
    elif passed:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "物料已经过法务审核，可正常发布。",
                },
            }
        )
    elements.append({"tag": "hr"})
    if passed:
        actions = [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                "type": "primary",
                "url": kanban_url,
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📋 查看物料详情"},
                "type": "default",
                "url": detail_url,
            },
        ]
    else:
        actions = [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                "type": "default",
                "url": kanban_url,
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✏️ 去修改物料"},
                "type": "default",
                "url": detail_url,
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ 修改完成，重新提交"},
                "type": "primary",
                "value": _action_value("resubmit", record_id, round_number),
            },
        ]
    elements.append({"tag": "action", "actions": actions})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"{'✅ 物料已通过法务审核' if passed else '📝 物料需修改后重新提交'} #{serial}",
            },
            "template": "green" if passed else "orange",
        },
        "elements": elements,
    }


def build_final_failure_card(
    record_id: str, *, round_number: Optional[int] = None
) -> dict:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": FINAL_FAILURE_TITLE},
            "template": "orange",
        },
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "plain_text", "content": FINAL_FAILURE_BODY},
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": FINAL_FAILURE_BUTTON},
                        "type": "primary",
                        "value": _action_value(
                            "start_ai_review", record_id, round_number
                        ),
                    }
                ],
            },
        ],
    }


def build_card(
    card_type: str, record_id: str, fields: dict, payload: Optional[dict] = None
) -> dict:
    payload = payload or {}
    round_number = payload.get("round")
    if card_type == "context_confirm":
        return build_context_confirm_card(
            record_id,
            fields,
            image_key=payload.get("image_key"),
            round_number=round_number,
        )
    if card_type == "initial_review":
        return build_initial_review_card(
            record_id,
            fields,
            image_key=payload.get("image_key"),
            round_number=round_number,
        )
    if card_type == "operator_result":
        return build_operator_result_card(record_id, fields, round_number=round_number)
    if card_type == "operator_more_info":
        return build_more_info_card(record_id, fields, round_number=round_number)
    if card_type == "legal_review":
        return build_legal_review_card(
            record_id, fields, workbench_url=_workbench_url()
        )
    if card_type == "operator_transferred":
        return build_operator_transferred_card(record_id, fields)
    if card_type == "verdict":
        return build_verdict_card(record_id, fields, round_number=round_number)
    if card_type == "final_failure":
        return build_final_failure_card(record_id, round_number=round_number)
    raise ValueError("unknown card type")


def _short(raw: Any, max_len: int) -> str:
    text = _text(raw)
    for separator in ("；", "\n", ";"):
        index = text.find(separator)
        if index > 0:
            return text[:index].strip()
    return text[:max_len].strip() + ("…" if len(text) > max_len else "")


def _workbench_url() -> str:
    try:
        import config

        return str(getattr(config, "WORKBENCH_URL", "http://localhost:5001"))
    except ImportError:
        return "http://localhost:5001"


def _action_value(action: str, record_id: str, round_number: Optional[int]) -> dict:
    value = {"action": action, "record_id": record_id}
    if round_number is not None:
        value["round"] = int(round_number)
    return value
