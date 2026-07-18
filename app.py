"""
法务工作台后端 — 对接 v4 多维表格

v4 五段字段命名:
  ① 运营提交段 / ② AI预审段（给运营）/ ③ AI审核段（给法务）
  ④ 法务裁决段 / ⑤ 流转沉淀段
"""
from flask import Flask, render_template, jsonify, request
import datetime
import threading

import feishu_api
import preference_memory
from fields_v4 import (
    # 运营段
    F_物料编号, F_行业领域, F_物料内容, F_物料附件, F_提交人, F_提交时间,
    F_紧急程度, F_补充背景资料,
    # 美妆专属
    F_美妆_物料类型, F_美妆_投放平台, F_美妆_产品品类,
    F_美妆_产品备案名称, F_美妆_物料涉及场景, F_美妆_核心宣称功效,
    # 游戏专属
    F_游戏_物料类型, F_游戏_投放平台, F_游戏_产品品类,
    F_游戏_游戏名称, F_游戏_物料涉及场景, F_游戏_IP名称,
    # 保健食品专属
    F_保健食品_物料类型, F_保健食品_投放平台, F_保健食品_产品品类,
    F_保健食品_物料涉及场景, F_保健食品_核心宣称功效,
    F_保健食品_产品备案名称, F_保健食品_批准文号,
    # AI预审段
    F_预审_风险等级, F_预审_命中要点, F_预审_修改建议,
    F_预审_运营修改记录, F_预审_运营是否采纳建议,
    # AI审核段
    F_审核_审核模式, F_审核_审核意见, F_审核_关键实体抽取,
    F_审核_高风险词命中, F_审核_平台规则预检, F_审核_备案核查结果,
    F_审核_推荐违规类型, F_审核_推荐风险等级,
    # 法务段
    F_法务_AI意见评价, F_法务_物料裁决, F_法务_异议字段,
    F_法务_补充或驳回理由, F_法务_驳回正确判定, F_法务_最终修改意见,
    F_法务_批注, F_法务_复核时间,
    # 流转段
    F_流转_当前状态, F_流转_反馈类型, F_流转_驳回次数,
    # 行业专属投放平台（规则沉淀时读取）
    F_美妆_投放平台, F_游戏_投放平台, F_保健食品_投放平台,
)

app = Flask(__name__)

# ===== 飞书卡片回调 =====

@app.route("/feishu/card", methods=["POST"])
def feishu_card_callback():
    """
    飞书互动卡片按钮回调入口。

    飞书在两种情况下会 POST 到这里：
    1. 首次配置时发 challenge 验证请求 → 原样返回 challenge 字段
    2. 运营点击卡片按钮时 → 解析 action.value，触发 AI 审核
    """
    body = request.json or {}

    # --- challenge 验证（飞书首次保存 URL 时发送）---
    if body.get("type") == "url_verification":
        return jsonify({"challenge": body.get("challenge", "")})

    # --- 卡片按钮点击 ---
    action = body.get("action", {})
    value  = action.get("value", {})
    act    = value.get("action", "")

    if act == "start_ai_review":
        record_id = value.get("record_id", "")
        if not record_id:
            return jsonify({"toast": {"type": "error", "content": "缺少 record_id"}}), 400

        # 异步触发审核（避免超时）
        import threading
        threading.Thread(target=_run_review, args=(record_id,), daemon=True).start()

        # 立即告知飞书：按钮点击已受理（卡片上显示 toast）
        return jsonify({
            "toast": {"type": "success", "content": "AI 审核已启动，请稍候…"}
        })

    return jsonify({}), 200


def _run_review(record_id: str):
    """在后台线程中执行 AI 审核（predictor 就绪后替换内部逻辑）"""
    try:
        rec = feishu_api.get_record(record_id)
        fields = rec.get("fields", {})
        print(f"[card_callback] 收到审核触发 record_id={record_id}")

        # TODO: 调用 predictor.review(fields) 并回写结果
        # 目前先把状态推进到"AI预审中"，占位
        feishu_api.update_record(record_id, {"⑤流转·当前状态": "AI预审中"})
        print(f"[card_callback] 状态已推进 → AI预审中")
    except Exception as e:
        print(f"[card_callback] 审核触发异常: {e}")


# ===== 工具函数 =====

def _name_of_user(raw):
    """飞书 User 字段值 → 名字（兼容 list 和 dict 两种格式）"""
    if isinstance(raw, list) and raw:
        u = raw[0]
        return u.get("name") or u.get("en_name") or ""
    if isinstance(raw, dict):
        return raw.get("name") or raw.get("en_name") or ""
    if isinstance(raw, str):
        return raw
    return ""


def _ts_to_str(raw):
    """毫秒时间戳 → yyyy-MM-dd HH:mm"""
    if not raw:
        return ""
    try:
        dt = datetime.datetime.fromtimestamp(int(raw) / 1000)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(raw)


def _as_list(raw):
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw] if raw else []


def _as_text(raw):
    """飞书富文本字段可能是 [{type:'text', text:'...'}]"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        # 取所有 text 拼接
        out = []
        for seg in raw:
            if isinstance(seg, dict):
                t = seg.get("text") or seg.get("name") or ""
                if t: out.append(t)
            else:
                out.append(str(seg))
        return "".join(out)
    if isinstance(raw, dict):
        return raw.get("text") or raw.get("name") or ""
    return str(raw)


# ===== 路由 =====

@app.route("/")
def index():
    return render_template("workbench.html")


@app.route("/api/records")
def get_records():
    """获取多维表格全部记录（按风险等级排序）"""
    try:
        raw_records = feishu_api.list_all_records()
        records = [normalize_record(it.get("record_id"), it.get("fields", {}))
                   for it in raw_records]

        risk_order = {"高风险": 0, "中风险": 1, "低风险": 2,
                      "高": 0, "中": 1, "低": 2}
        records.sort(key=lambda r: risk_order.get(r["风险等级"], 9))
        return jsonify(records)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/records/<record_id>/review", methods=["POST"])
def submit_review(record_id):
    """
    法务提交裁决 — 6种组合逻辑，回写飞书 v4 多维表格

    | AI意见评价  | 物料裁决 | 反馈类型  | 学习方向                |
    |------------|---------|----------|------------------------|
    | 同意无补充  | 通过    | 无       | —                      |
    | 同意无补充  | 不通过  | 无       | —                      |
    | 同意有补充  | 通过    | refine   | AI需补充此类分析        |
    | 同意有补充  | 不通过  | refine   | AI需补充此类分析        |
    | 驳回       | 通过    | override | AI误判违规，实际合规    |
    | 驳回       | 不通过  | override | AI判定类型/程度有误     |
    """
    data = request.json or {}
    ai_opinion = data.get("ai_opinion", "")
    verdict = data.get("verdict", "")

    if not ai_opinion or not verdict:
        return jsonify({"success": False, "message": "AI意见评价和物料裁决为必填项"}), 400

    if ai_opinion == "同意有补充" and not data.get("supplement_reason", "").strip():
        return jsonify({"success": False, "message": "同意有补充时补充意见为必填"}), 400

    if ai_opinion == "驳回":
        if not data.get("objection_fields"):
            return jsonify({"success": False, "message": "驳回时异议字段为必选"}), 400
        if not data.get("reject_reason", "").strip():
            return jsonify({"success": False, "message": "驳回时理由为必填"}), 400
        if not data.get("correct_judgment", "").strip():
            return jsonify({"success": False, "message": "驳回时正确判定为必填"}), 400

    if verdict == "不通过" and not data.get("final_suggestion", "").strip():
        return jsonify({"success": False, "message": "物料不通过时修改意见为必填"}), 400

    review_status = "已通过" if verdict == "通过" else "需修改"
    feedback_type = {"同意无补充": "无", "同意有补充": "refine", "驳回": "override"}.get(ai_opinion, "无")

    # 组装回写字段（v4 字段名）
    update_fields = {
        F_法务_AI意见评价: ai_opinion,
        F_法务_物料裁决: verdict,
        F_流转_当前状态: review_status,
        F_流转_反馈类型: feedback_type,
        F_法务_复核时间: int(datetime.datetime.now().timestamp() * 1000),
    }

    objection = data.get("objection_fields", [])
    if objection:
        update_fields[F_法务_异议字段] = objection

    reason = (data.get("reject_reason") or data.get("supplement_reason") or "").strip()
    if reason:
        update_fields[F_法务_补充或驳回理由] = reason

    correct = (data.get("correct_judgment") or "").strip()
    if correct:
        update_fields[F_法务_驳回正确判定] = correct

    final_sug = (data.get("final_suggestion") or "").strip()
    if final_sug:
        update_fields[F_法务_最终修改意见] = final_sug

    note = (data.get("note") or "").strip()
    if note:
        update_fields[F_法务_批注] = note

    # 驳回时累加驳回次数
    if ai_opinion == "驳回":
        try:
            cur = feishu_api.get_record(record_id)
            old = cur.get("fields", {}).get(F_流转_驳回次数) or 0
            update_fields[F_流转_驳回次数] = int(old) + 1
        except Exception:
            update_fields[F_流转_驳回次数] = 1

    try:
        feishu_api.update_record(record_id, update_fields)

        # 规则沉淀：refine / override 触发存储纠正记录
        if feedback_type in ("refine", "override"):
            try:
                rec = feishu_api.get_record(record_id)
                f = rec.get("fields", {})
                content_snippet = _as_text(f.get(F_物料内容, ""))[:120]
                industry  = f.get(F_行业领域, "")
                _platform_field = {
                    "美妆": F_美妆_投放平台,
                    "游戏": F_游戏_投放平台,
                    "保健食品": F_保健食品_投放平台,
                }
                platform_raw = f.get(_platform_field.get(industry, ""), "")
                platform = "、".join(platform_raw) if isinstance(platform_raw, list) else str(platform_raw or "")
                ai_risk   = _norm_risk(f.get(F_审核_推荐风险等级, ""))
                ai_vtypes = f.get(F_审核_推荐违规类型, [])
                if not isinstance(ai_vtypes, list):
                    ai_vtypes = [str(ai_vtypes)] if ai_vtypes else []
                preference_memory.save_correction(
                    record_id        = record_id,
                    content_snippet  = content_snippet,
                    industry         = industry,
                    platform         = platform,
                    ai_risk_level    = ai_risk,
                    ai_violation_types = ai_vtypes,
                    feedback_type    = feedback_type,
                    objection_fields = data.get("objection_fields", []),
                    correct_judgment = (data.get("correct_judgment") or "").strip(),
                    reason           = (data.get("reject_reason") or data.get("supplement_reason") or "").strip(),
                )
            except Exception as me:
                print(f"[app] 规则沉淀写入失败（非致命）: {me}")

        # 仅在需要通知运营时异步推卡片（修改裁决时若关键字段未变则跳过）
        if data.get("notify_operator", True):
            threading.Thread(
                target=_notify_operator_verdict,
                args=(record_id, ai_opinion, verdict,
                      data.get("final_suggestion", "").strip(),
                      data.get("supplement_reason", "").strip(),
                      data.get("reject_reason", "").strip()),
                daemon=True,
            ).start()
        return jsonify({
            "success": True,
            "message": "裁决已提交",
            "status": review_status,
            "feedback_type": feedback_type,
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"回写飞书失败: {str(e)}"}), 500


def _notify_operator_verdict(record_id: str, ai_opinion: str, verdict: str,
                              final_suggestion: str, supplement: str, reject_reason: str):
    """
    法务裁决完成后，根据 6 种组合给运营推飞书通知卡片。
    """
    try:
        rec = feishu_api.get_record(record_id)
        fields = rec.get("fields", {})
        # 取提交人 open_id
        submitter_raw = fields.get(F_提交人)
        if isinstance(submitter_raw, list) and submitter_raw:
            open_id = submitter_raw[0].get("id") or submitter_raw[0].get("open_id")
        elif isinstance(submitter_raw, dict):
            open_id = submitter_raw.get("id") or submitter_raw.get("open_id")
        else:
            open_id = None

        if not open_id:
            print(f"[app] ⚠ 提交人 open_id 为空，无法发送裁决通知 record_id={record_id}")
            return

        bitable_url = (
            f"https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb"
            f"?table=tblL8R7yL1rCeU7m&view=vewMSBI3s8&record={record_id}"
        )
        kanban_url = (
            f"https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb"
            f"?table=tblL8R7yL1rCeU7m&view=vewEddfI3c&record={record_id}"
        )
        form_url = "https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb?table=tblL8R7yL1rCeU7m&view=vew3KEItkB"
        serial = str(fields.get(F_物料编号, record_id[-6:]))

        # 物料内容预览（取前60字）
        content_raw = fields.get(F_物料内容, "")
        content_text = _as_text(content_raw)
        preview = content_text[:60] + ("…" if len(content_text) > 60 else "")

        passed = (verdict == "通过")
        overridden = (ai_opinion == "驳回" and passed)

        # 卡片颜色与标题
        if passed:
            template = "green"
            title = f"✅ 物料已通过法务审核 #{serial}"
        else:
            template = "orange"
            title = f"📝 物料需修改后重新提交 #{serial}"

        # 正文内容块
        elements = []

        # 物料预览
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**物料内容**\n{preview}"},
        })

        # 不通过时给出修改意见，通过时给出简短说明
        if not passed and final_suggestion:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**修改意见**\n{final_suggestion}"},
            })
        elif passed:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "物料已经过法务审核，可正常发布。"},
            })

        elements.append({"tag": "hr"})

        # 通过：查看AI审核意见 + 查看详情；不通过：去修改 + 重新提交 + 查看AI审核意见
        if passed:
            actions = [
                {"tag": "button",
                 "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                 "type": "primary", "url": kanban_url},
                {"tag": "button",
                 "text": {"tag": "plain_text", "content": "📋 查看物料详情"},
                 "type": "default", "url": bitable_url},
            ]
        else:
            actions = [
                {"tag": "button",
                 "text": {"tag": "plain_text", "content": "🔍 查看AI审核意见"},
                 "type": "default", "url": kanban_url},
                {"tag": "button",
                 "text": {"tag": "plain_text", "content": "✏️ 去修改物料"},
                 "type": "default", "url": form_url},
                {"tag": "button",
                 "text": {"tag": "plain_text", "content": "✅ 修改完成，重新提交"},
                 "type": "primary",
                 "value": {"action": "resubmit", "record_id": record_id}},
            ]
        elements.append({"tag": "action", "actions": actions})

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": template,
            },
            "elements": elements,
        }

        feishu_api.send_card_to(open_id, card)
        print(f"[app] ✓ 裁决通知已推送给运营 record_id={record_id} verdict={verdict} ai_opinion={ai_opinion}")

    except Exception as e:
        print(f"[app] ✗ 裁决通知发送失败 record_id={record_id}: {e}")


def _norm_risk(val):
    """v4 风险等级单选值('高'/'中'/'低') → 兼容前端('高风险'/'中风险'/'低风险')"""
    if not val: return ""
    s = str(val).strip()
    mapping = {"高": "高风险", "中": "中风险", "低": "低风险",
               "无明显风险": "低风险"}
    return mapping.get(s, s)


def _get_platform(fields, industry=None):
    """根据行业读取对应投放平台字段，返回逗号拼接字符串"""
    if industry is None:
        industry = fields.get(F_行业领域, "")
    _platform_field = {
        "美妆": F_美妆_投放平台,
        "游戏": F_游戏_投放平台,
        "保健食品": F_保健食品_投放平台,
    }
    raw = fields.get(_platform_field.get(industry, ""), "")
    return "、".join(raw) if isinstance(raw, list) else str(raw or "")


def normalize_record(record_id, fields):
    """飞书 v4 原始字段 → 前端格式（兼容旧前端字段名）"""
    return {
        "id": record_id,
        # 运营段
        "物料编号": str(fields.get(F_物料编号, "")),  # 自动编号字段直接是字符串
        "行业领域": fields.get(F_行业领域, ""),
        "投放平台": _get_platform(fields),
        "物料内容": _as_text(fields.get(F_物料内容)),
        "物料附件": [
            {"file_token": a.get("file_token"), "name": a.get("name", "")}
            for a in _as_list(fields.get(F_物料附件))
            if isinstance(a, dict) and a.get("file_token")
        ],
        "提交人": _name_of_user(fields.get(F_提交人)),
        "提交时间": _ts_to_str(fields.get(F_提交时间) or fields.get("创建时间")),
        "紧急程度": fields.get(F_紧急程度, ""),

        # AI预审段（给运营看的轻量审核）
        "预审_风险等级": _norm_risk(fields.get(F_预审_风险等级, "")),
        "预审_命中要点": _as_text(fields.get(F_预审_命中要点)),
        "预审_修改建议": _as_text(fields.get(F_预审_修改建议)),
        "预审_运营修改记录": _as_text(fields.get(F_预审_运营修改记录)),
        "预审_运营是否采纳建议": fields.get(F_预审_运营是否采纳建议, ""),

        # AI审核段（给法务看的深度审核）
        "审核模式": fields.get(F_审核_审核模式, ""),
        "AI审核意见": _as_text(fields.get(F_审核_审核意见)),
        "关键实体抽取": _as_text(fields.get(F_审核_关键实体抽取)),
        "AI抽取-高风险词命中": _as_text(fields.get(F_审核_高风险词命中)),
        "平台规则预检": _as_text(fields.get(F_审核_平台规则预检)),
        "AI抽取-备案核查结果": _as_text(fields.get(F_审核_备案核查结果)),
        "违规类型": _as_list(fields.get(F_审核_推荐违规类型, [])),
        "风险等级": _norm_risk(fields.get(F_审核_推荐风险等级, "")),

        # 法务段
        "AI意见评价": fields.get(F_法务_AI意见评价, ""),
        "物料裁决": fields.get(F_法务_物料裁决, ""),
        "异议字段": _as_list(fields.get(F_法务_异议字段, [])),
        "法务补充或驳回理由": _as_text(fields.get(F_法务_补充或驳回理由)),
        "驳回正确判定": _as_text(fields.get(F_法务_驳回正确判定)),
        "最终修改意见": _as_text(fields.get(F_法务_最终修改意见)),
        "法务批注": _as_text(fields.get(F_法务_批注)),

        # 行业专属 — 美妆
        "美妆_物料类型": fields.get(F_美妆_物料类型, ""),
        "美妆_产品品类": fields.get(F_美妆_产品品类, ""),
        "美妆_产品备案名称": _as_text(fields.get(F_美妆_产品备案名称)),
        "美妆_物料涉及场景": _as_list(fields.get(F_美妆_物料涉及场景, [])),
        "美妆_核心宣称功效": _as_text(fields.get(F_美妆_核心宣称功效)),

        # 行业专属 — 游戏
        "游戏_物料类型": fields.get(F_游戏_物料类型, ""),
        "游戏_产品品类": fields.get(F_游戏_产品品类, ""),
        "游戏_游戏名称": _as_text(fields.get(F_游戏_游戏名称)),
        "游戏_物料涉及场景": _as_list(fields.get(F_游戏_物料涉及场景, [])),
        "游戏_IP名称": _as_text(fields.get(F_游戏_IP名称)),

        # 行业专属 — 保健食品
        "保健食品_物料类型": fields.get(F_保健食品_物料类型, ""),
        "保健食品_产品品类": fields.get(F_保健食品_产品品类, ""),
        "保健食品_产品备案名称": _as_text(fields.get(F_保健食品_产品备案名称)),
        "保健食品_批准文号": _as_text(fields.get(F_保健食品_批准文号)),
        "保健食品_物料涉及场景": _as_list(fields.get(F_保健食品_物料涉及场景, [])),
        "保健食品_核心宣称功效": _as_text(fields.get(F_保健食品_核心宣称功效)),

        # 通用补充
        "补充背景资料": _as_text(fields.get(F_补充背景资料)),

        # 流转段
        "审核状态": fields.get(F_流转_当前状态, ""),
        "反馈类型": fields.get(F_流转_反馈类型, ""),
        "驳回次数": fields.get(F_流转_驳回次数, 0),
    }


@app.route("/api/attachment/<file_token>")
def proxy_attachment(file_token):
    """代理下载飞书附件图片，压缩后返回，本地磁盘缓存加速"""
    import os, io
    from PIL import Image
    from flask import Response

    cache_dir = "/tmp/adsure_img_cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, file_token + ".thumb.jpg")

    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            thumb_bytes = f.read()
    else:
        try:
            img_bytes = feishu_api.download_attachment(file_token)
        except Exception as e:
            return jsonify({"error": str(e)}), 404

        try:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            img.thumbnail((900, 900), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75, optimize=True)
            thumb_bytes = buf.getvalue()
            with open(cache_path, "wb") as f:
                f.write(thumb_bytes)
        except Exception:
            # Pillow 处理失败则直接返回原图
            thumb_bytes = img_bytes

    resp = Response(thumb_bytes, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# ===== 规则库 API =====

@app.route("/api/corrections")
def list_corrections():
    """返回全部纠正记录（法务规则库查阅）"""
    return jsonify(preference_memory.list_all())


@app.route("/api/corrections/<correction_id>/status", methods=["POST"])
def update_correction_status(correction_id):
    """切换纠正记录状态 active / paused"""
    data = request.json or {}
    status = data.get("status", "paused")
    if status not in ("active", "paused"):
        return jsonify({"success": False, "message": "status 必须为 active 或 paused"}), 400
    ok = preference_memory.set_status(correction_id, status)
    return jsonify({"success": ok})


@app.route("/api/corrections/<correction_id>", methods=["DELETE"])
def delete_correction(correction_id):
    """永久删除一条纠正记录"""
    ok = preference_memory.delete_correction(correction_id)
    return jsonify({"success": ok})


# ===== 案例库 API =====

@app.route("/api/records/<record_id>/cases")
def get_cases(record_id):
    """
    代理调用案例库检索接口，返回与当前物料相关的历史处罚案例。
    失败或超时时静默降级返回空数组，不影响主审核流程和飞书状态。
    """
    try:
        from config import CASE_ENGINE_URL, CASE_ENGINE_API_KEY
        import requests as _requests

        rec = feishu_api.get_record(record_id)
        fields = rec.get("fields", {})

        industry = _as_text(fields.get(F_行业领域, ""))
        content  = _as_text(fields.get(F_物料内容, ""))
        _platform_field = {
            "美妆":     F_美妆_投放平台,
            "游戏":     F_游戏_投放平台,
            "保健食品": F_保健食品_投放平台,
        }
        platform_raw = fields.get(_platform_field.get(industry, ""), "")
        platform = platform_raw if isinstance(platform_raw, list) else ([str(platform_raw)] if platform_raw else [])

        resp = _requests.post(
            f"{CASE_ENGINE_URL}/cases/retrieve",
            headers={"X-API-Key": CASE_ENGINE_API_KEY, "Content-Type": "application/json"},
            json={"content": content, "industry": industry, "platform": platform, "top_k": 3},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"案例库返回错误: {data.get('msg')} (code={data.get('code')})")

        cases = data.get("data", {}).get("cases", [])
        return jsonify({"cases": cases, "record_id": record_id})

    except Exception as e:
        print(f"[app] 案例库检索失败（静默降级）record_id={record_id}: {e}")
        return jsonify({"cases": [], "record_id": record_id})


if __name__ == "__main__":
    # use_reloader=False：避免 debug 模式启动双进程，防止 stop.sh 漏杀子进程导致端口占用
    app.run(host="0.0.0.0", debug=True, port=5001, use_reloader=False)
