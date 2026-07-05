"""
法务工作台后端 — 对接 v4 多维表格

v4 五段字段命名:
  ① 运营提交段 / ② AI预审段（给运营）/ ③ AI审核段（给法务）
  ④ 法务裁决段 / ⑤ 流转沉淀段
"""
from flask import Flask, render_template, jsonify, request
import datetime

import feishu_api
from fields_v4 import (
    # 运营段
    F_物料编号, F_行业领域, F_物料内容, F_提交人, F_提交时间,
    F_紧急程度,
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
    """飞书 User 字段值 → 名字"""
    if isinstance(raw, list) and raw:
        u = raw[0]
        return u.get("name") or u.get("en_name") or ""
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
        return jsonify({
            "success": True,
            "message": "裁决已提交",
            "status": review_status,
            "feedback_type": feedback_type,
        })
    except Exception as e:
        return jsonify({"success": False, "message": f"回写飞书失败: {str(e)}"}), 500


def _norm_risk(val):
    """v4 风险等级单选值('高'/'中'/'低') → 兼容前端('高风险'/'中风险'/'低风险')"""
    if not val: return ""
    s = str(val).strip()
    mapping = {"高": "高风险", "中": "中风险", "低": "低风险",
               "无明显风险": "低风险"}
    return mapping.get(s, s)


def normalize_record(record_id, fields):
    """飞书 v4 原始字段 → 前端格式（兼容旧前端字段名）"""
    return {
        "id": record_id,
        # 运营段
        "物料编号": str(fields.get(F_物料编号, "")),  # 自动编号字段直接是字符串
        "行业领域": fields.get(F_行业领域, ""),
        "物料内容": _as_text(fields.get(F_物料内容)),
        "提交人": _name_of_user(fields.get(F_提交人)),
        "提交时间": _ts_to_str(fields.get(F_提交时间)),
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

        # 流转段
        "审核状态": fields.get(F_流转_当前状态, ""),
        "反馈类型": fields.get(F_流转_反馈类型, ""),
        "驳回次数": fields.get(F_流转_驳回次数, 0),
    }


if __name__ == "__main__":
    app.run(debug=True, port=5001)
