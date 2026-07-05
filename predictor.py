"""
审心 · AI 审核核心模块

调用入口（供 bot_listener.py 使用）：
    from predictor import review
    review(record_id)

执行顺序：
    1. build_context       — 上下文重建：从多维表格读取物料，拼成结构化上下文
    2. run_rule_engine     — 规则引擎（TODO：对接队友 API，目前用本地 JSON 占位）
    3. call_llm            — 调用大模型，生成六段式审核报告
    4. write_back          — 回写 ②③ 段字段，更新流转状态
"""

import json
import datetime
from pathlib import Path

from feishu_api import get_record, update_record
from fields_v4 import (
    # 运营段
    F_行业领域, F_物料内容, F_补充背景资料, F_紧急程度,
    # 美妆
    F_美妆_物料类型, F_美妆_投放平台, F_美妆_产品品类,
    F_美妆_产品备案名称, F_美妆_物料涉及场景, F_美妆_核心宣称功效,
    # 游戏
    F_游戏_物料类型, F_游戏_投放平台, F_游戏_产品品类,
    F_游戏_游戏名称, F_游戏_物料涉及场景, F_游戏_IP名称,
    # 保健食品
    F_保健食品_物料类型, F_保健食品_投放平台, F_保健食品_产品品类,
    F_保健食品_物料涉及场景, F_保健食品_核心宣称功效,
    F_保健食品_产品备案名称, F_保健食品_批准文号,
    # AI预审段
    F_预审_风险等级, F_预审_命中要点, F_预审_修改建议, F_预审_时间,
    # AI审核段
    F_审核_审核模式, F_审核_模式推荐理由, F_审核_审核意见,
    F_审核_关键实体抽取, F_审核_高风险词命中, F_审核_平台规则预检,
    F_审核_推荐违规类型, F_审核_推荐风险等级, F_审核_审核时间,
    # 流转段
    F_流转_当前状态,
)


# ── 工具函数 ────────────────────────────────────────────────

def _text(raw) -> str:
    """飞书字段值 → 纯文本（兼容富文本数组、字符串、字典）"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(
            seg.get("text", "") if isinstance(seg, dict) else str(seg)
            for seg in raw
        )
    if isinstance(raw, dict):
        return raw.get("text") or raw.get("name") or ""
    return str(raw)


# ── 阶段一：上下文重建 ──────────────────────────────────────

# 各行业专属字段映射
_INDUSTRY_FIELDS = {
    "美妆": {
        "物料类型":     F_美妆_物料类型,
        "投放平台":     F_美妆_投放平台,
        "产品品类":     F_美妆_产品品类,
        "产品备案名称": F_美妆_产品备案名称,
        "物料涉及场景": F_美妆_物料涉及场景,
        "核心宣称功效": F_美妆_核心宣称功效,
    },
    "游戏": {
        "物料类型":     F_游戏_物料类型,
        "投放平台":     F_游戏_投放平台,
        "产品品类":     F_游戏_产品品类,
        "游戏名称":     F_游戏_游戏名称,
        "物料涉及场景": F_游戏_物料涉及场景,
        "IP名称":       F_游戏_IP名称,
    },
    "保健食品": {
        "物料类型":     F_保健食品_物料类型,
        "投放平台":     F_保健食品_投放平台,
        "产品品类":     F_保健食品_产品品类,
        "物料涉及场景": F_保健食品_物料涉及场景,
        "核心宣称功效": F_保健食品_核心宣称功效,
        "产品备案名称": F_保健食品_产品备案名称,
        "批准文号":     F_保健食品_批准文号,
    },
}


def build_context(record_id: str) -> dict:
    """
    从多维表格读取一条记录，重建完整审核上下文。

    返回 dict：
    {
        "record_id":      str,
        "industry":       str,   # 行业领域
        "content":        str,   # 物料内容（核心文案）
        "supplement":     str,   # 补充背景资料
        "urgency":        str,   # 紧急程度
        "platform":       str,   # 投放平台（行业专属）
        "material_type":  str,   # 物料类型（行业专属）
        "product_category": str, # 产品品类（行业专属）
        "extras":         dict,  # 其余行业专属字段 {展示名: 值}
    }
    """
    rec = get_record(record_id)
    fields = rec.get("fields", {})

    industry = _text(fields.get(F_行业领域, ""))
    content   = _text(fields.get(F_物料内容, ""))
    supplement = _text(fields.get(F_补充背景资料, ""))
    urgency   = _text(fields.get(F_紧急程度, "普通"))

    # 读取行业专属字段
    industry_map = _INDUSTRY_FIELDS.get(industry, {})
    platform       = _text(fields.get(industry_map.get("投放平台", ""), ""))
    material_type  = _text(fields.get(industry_map.get("物料类型", ""), ""))
    product_category = _text(fields.get(industry_map.get("产品品类", ""), ""))

    # 其余行业专属字段（除了投放平台/物料类型/产品品类，已单独提取）
    skip = {"投放平台", "物料类型", "产品品类"}
    extras = {}
    for label, field_key in industry_map.items():
        if label not in skip:
            val = _text(fields.get(field_key, ""))
            if val:
                extras[label] = val

    return {
        "record_id":        record_id,
        "industry":         industry,
        "content":          content,
        "supplement":       supplement,
        "urgency":          urgency,
        "platform":         platform,
        "material_type":    material_type,
        "product_category": product_category,
        "extras":           extras,
    }


def format_context_for_prompt(ctx: dict) -> str:
    """
    把上下文 dict 格式化成 LLM prompt 里的「物料信息」文本块。
    """
    lines = []
    lines.append(f"【物料内容】\n{ctx['content']}")
    lines.append(f"\n【行业领域】{ctx['industry']}")

    if ctx["platform"]:
        lines.append(f"【投放平台】{ctx['platform']}")
    if ctx["material_type"]:
        lines.append(f"【物料类型】{ctx['material_type']}")
    if ctx["product_category"]:
        lines.append(f"【产品品类】{ctx['product_category']}")

    if ctx["extras"]:
        lines.append("\n【行业专属信息】")
        for label, val in ctx["extras"].items():
            lines.append(f"- {label}：{val}")

    if ctx["supplement"].strip():
        lines.append(f"\n【补充背景资料】\n{ctx['supplement']}")

    return "\n".join(lines)


# ── 阶段二～四（TODO）────────────────────────────────────────

def recommend_mode(ctx: dict) -> str:
    """
    推荐审核模式：标准 / 极速 / 深度。
    TODO：等团队给出具体分配依据后替换此逻辑。
    当前：默认返回「标准」。
    """
    return "标准"


def call_teammate_engine(ctx: dict, mode: str) -> list:
    """
    调用队友规则引擎，返回命中规则列表。
    TODO：等队友提供 HTTP API 后替换。
    当前：返回空列表，LLM 根据通用原则独立审核。
    """
    # 示例（队友 API 就绪后取消注释）：
    # import requests
    # resp = requests.post("http://teammate-api/check", json={
    #     "content": ctx["content"],
    #     "industry": ctx["industry"],
    #     "mode": mode,
    # }, timeout=10)
    # return resp.json().get("hits", [])
    return []


def _decide_routing(hits: list, llm_routing: str) -> str:
    """
    综合规则引擎命中结果和 LLM 建议，决定最终路由。
    规则引擎优先：只要有一条规则指向法务，就去法务。
    """
    routings = [r.get("default_routing", "") for r in hits]
    if "法务" in routings:
        return "待法务复核"
    if "运营补资料" in routings:
        return "运营补资料"
    if llm_routing == "法务":
        return "待法务复核"
    return "待运营修改"


def _format_rules_for_prompt(rules: list) -> str:
    """把命中规则格式化成 prompt 文本"""
    if not rules:
        return "【规则引擎】本次未命中预设规则，请根据广告法通用原则进行审核。"
    lines = ["【命中规则】"]
    for r in rules:
        lines.append(
            f"- [{r.get('rule_type','?')}] {r.get('law_name','?')}"
            f"（违规类型：{r.get('violation_type','?')}，"
            f"路由建议：{r.get('default_routing','?')}）"
        )
    return "\n".join(lines)


def call_llm(ctx: dict, rules: list, mode: str = "标准") -> dict:
    """
    调用大模型，生成结构化审核报告（JSON 输出）。
    返回 dict，key 与多维表格字段对应。
    """
    import anthropic
    from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

    client = anthropic.Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    material_text = format_context_for_prompt(ctx)
    rules_text    = _format_rules_for_prompt(rules)

    system_prompt = """\
你是一名专业的广告合规审核专家，熟悉中国《广告法》《消费者权益保护法》《食品安全法》等法律法规及各平台运营规则。
请对用户提交的广告物料进行合规审核，输出严格 JSON 格式的审核报告，不得包含任何 JSON 以外的文字。

输出 JSON 结构：
{
  "预审_风险等级": "高" | "中" | "低",
  "预审_命中要点": "一句话概括最核心的合规风险",
  "预审_修改建议": "给运营人员的简明修改建议（100字以内）",
  "审核_审核意见": "完整六段式审核报告：①风险定性 ②违禁词鉴别 ③违规类型 ④法律依据 ⑤修改建议 ⑥风险定级",
  "审核_关键实体抽取": "品牌名、产品名、功效词、平台名（逗号分隔）",
  "审核_高风险词命中": "命中的违禁词或高风险词（逗号分隔，无则填'无'）",
  "审核_平台规则预检": "投放平台相关规则命中情况（一句话）",
  "审核_推荐违规类型": ["违规类型1", "违规类型2"],
  "审核_推荐风险等级": "高" | "中" | "低",
  "routing": "运营" | "法务"
}

routing 字段判断标准：
- "运营"：违规类型明确、可直接改写，无需法务解释
- "法务"：需要法律解释、存在模糊地带、或涉及重大合规风险"""

    user_message = f"{material_text}\n\n{rules_text}"

    print(f"[predictor] 调用 LLM（模型={LLM_MODEL}）...")
    message = client.messages.create(
        model=LLM_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    # DeepSeek 可能返回 ThinkingBlock + TextBlock，找到有 .text 的那个
    text_block = next((b for b in message.content if hasattr(b, "text")), None)
    if text_block is None:
        raise ValueError(f"LLM 响应中未找到文本内容，content={message.content}")
    raw = text_block.text.strip()
    # 去掉可能的 markdown 代码块包裹
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw)
    print(f"[predictor] LLM 返回，风险等级={result.get('预审_风险等级')}")
    return result


def write_back(record_id: str, llm_result: dict, routing: str, mode: str = "标准"):
    """把审核结果回写到多维表格 ②③ 段，更新流转状态。"""
    now_ms = int(datetime.datetime.now().timestamp() * 1000)

    fields = {
        # ② AI预审段（运营可见）
        F_预审_风险等级:      llm_result.get("预审_风险等级", ""),
        F_预审_命中要点:      llm_result.get("预审_命中要点", ""),
        F_预审_修改建议:      llm_result.get("预审_修改建议", ""),
        F_预审_时间:          now_ms,
        # ③ AI审核段（法务可见）
        F_审核_审核模式:      mode,
        F_审核_模式推荐理由:  "（待分配依据上线后自动填写）",
        F_审核_审核意见:      llm_result.get("审核_审核意见", ""),
        F_审核_关键实体抽取:  llm_result.get("审核_关键实体抽取", ""),
        F_审核_高风险词命中:  llm_result.get("审核_高风险词命中", ""),
        F_审核_平台规则预检:  llm_result.get("审核_平台规则预检", ""),
        F_审核_推荐违规类型:  llm_result.get("审核_推荐违规类型", []),
        F_审核_推荐风险等级:  llm_result.get("审核_推荐风险等级", ""),
        F_审核_审核时间:      now_ms,
        # ⑤ 流转段
        F_流转_当前状态:      routing,
    }
    update_record(record_id, fields)
    print(f"[predictor] 回写完成，流转状态 → {routing}")


# ── 上下文缓存（跨两步调用） ─────────────────────────────────
# key: record_id, value: ctx dict
# 运营确认模式后，execute() 直接从缓存取，避免重复请求飞书 API
_ctx_cache: dict = {}


# ── 主入口：两步拆分 ─────────────────────────────────────────

def prepare(record_id: str) -> tuple:
    """
    第一步：上下文重建 + 推荐模式。
    由 bot_listener 在运营点「开启AI审核」后调用。
    返回 (ctx, recommended_mode)，供发模式确认卡片使用。
    """
    print(f"[predictor] 上下文重建 record_id={record_id}")
    ctx = build_context(record_id)
    print(f"[predictor] 重建完成，行业={ctx['industry']}，内容={len(ctx['content'])}字")

    mode = recommend_mode(ctx)
    print(f"[predictor] 推荐模式 → {mode}")

    _ctx_cache[record_id] = ctx   # 缓存，等运营确认后 execute() 取用
    return ctx, mode


def execute(record_id: str, mode: str):
    """
    第二步：正式审核。
    由 bot_listener 在运营确认模式后调用。
    """
    print(f"[predictor] 正式审核开始 record_id={record_id} mode={mode}")

    # 优先从缓存取上下文，避免重复请求
    ctx = _ctx_cache.pop(record_id, None)
    if ctx is None:
        print(f"[predictor] 缓存未命中，重新拉取上下文")
        ctx = build_context(record_id)

    # 调用队友规则引擎
    hits = call_teammate_engine(ctx, mode)
    print(f"[predictor] 规则引擎命中 {len(hits)} 条")

    # LLM 生成报告
    llm_result = call_llm(ctx, hits, mode)

    # 路由 + 回写
    routing = _decide_routing(hits, llm_result.get("routing", ""))
    write_back(record_id, llm_result, routing, mode)
    print(f"[predictor] 审核完成，routing={routing}")
    return routing, llm_result
