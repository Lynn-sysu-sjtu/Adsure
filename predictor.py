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
import re
import datetime
from pathlib import Path

from feishu_api import get_record, update_record
from ocr_preprocessor import extract_text_from_attachments
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
    F_审核_备案核查结果,
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
        # 富文本段落：每段是 {"text": "..."}
        # 多选字段：每段是普通字符串，用顿号拼接展示
        parts = []
        for seg in raw:
            if isinstance(seg, dict):
                parts.append(seg.get("text", ""))
            else:
                parts.append(str(seg))
        # 如果全是纯字符串（多选选项），用顿号拼接；富文本则直接 join
        if all(not isinstance(seg, dict) for seg in raw):
            return "、".join(parts)
        return "".join(parts)
    if isinstance(raw, dict):
        return raw.get("text") or raw.get("name") or ""
    return str(raw)


def _list(raw) -> list:
    """飞书多选字段值 → 字符串数组（用于传给规则引擎）"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(seg) if not isinstance(seg, dict) else seg.get("text", "") for seg in raw]
    if isinstance(raw, str) and raw:
        return [raw]
    return []


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
        "record_id":        str,
        "industry":         str,   # 行业领域
        "content":          str,   # 物料内容（核心文案）
        "supplement":       str,   # 补充背景资料
        "urgency":          str,   # 紧急程度
        "platform":         str,   # 投放平台，顿号拼接文本（供 LLM prompt 使用）
        "platform_list":    list,  # 投放平台，字符串数组（供规则引擎 API 使用）
        "material_type":    str,   # 物料类型（行业专属）
        "product_category": str,   # 产品品类（行业专属）
        "extras":           dict,  # 其余行业专属字段 {展示名: 值}
    }
    """
    rec = get_record(record_id)
    fields = rec.get("fields", {})

    industry   = _text(fields.get(F_行业领域, ""))
    content    = _text(fields.get(F_物料内容, ""))

    # 若文字内容为空，尝试从图片附件 OCR 提取
    if not content.strip():
        content = extract_text_from_attachments(record_id, fields)

    supplement = _text(fields.get(F_补充背景资料, ""))
    urgency    = _text(fields.get(F_紧急程度, "普通"))

    # 读取行业专属字段
    industry_map = _INDUSTRY_FIELDS.get(industry, {})
    platform_raw     = fields.get(industry_map.get("投放平台", ""), "")
    platform         = _text(platform_raw)          # 文本版，供 LLM prompt
    platform_list    = _list(platform_raw)          # 数组版，供规则引擎 API
    material_type    = _text(fields.get(industry_map.get("物料类型", ""), ""))
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
        "platform":         platform,        # 文本，供 LLM prompt
        "platform_list":    platform_list,   # 数组，供规则引擎 API
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


def call_teammate_engine(ctx: dict, mode: str):
    """
    调用队友规则引擎。
    - 引擎返回完整审核结果（dict with routing）时，execute() 直接使用，跳过本地 LLM。
    - 引擎返回命中规则列表（list）时，交给本地 LLM 生成报告。
    """
    from config import RULE_ENGINE_URL, RULE_ENGINE_API_KEY
    import requests as _requests

    resp = _requests.post(
        RULE_ENGINE_URL,
        headers={"X-API-Key": RULE_ENGINE_API_KEY, "Content-Type": "application/json"},
        json={
            "record_id":        ctx["record_id"],
            "industry":         ctx["industry"],
            "content":          ctx["content"],
            "platform":         ctx["platform_list"],   # 数组，如 ["抖音", "小红书"]
            "material_type":    ctx["material_type"],
            "product_category": ctx["product_category"],
            "urgency":          ctx["urgency"],
            "supplement":       ctx["supplement"],
            "extras":           ctx["extras"],
            "mode":             mode,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"规则引擎返回错误: {data.get('msg')} (code={data.get('code')})")
    return data.get("data", {})


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
    import preference_memory

    client = anthropic.Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

    material_text = format_context_for_prompt(ctx)
    rules_text    = _format_rules_for_prompt(rules)

    # Few-shot 注入：召回法务历史纠正案例
    corrections = preference_memory.retrieve_relevant(
        ctx["content"], industry=ctx["industry"], top_k=3
    )
    corrections_text = preference_memory.format_for_prompt(corrections)
    if corrections_text:
        print(f"[predictor] 注入 {len(corrections)} 条历史纠正案例")

    system_prompt = """\
你是一名专业的广告合规审核专家，熟悉中国《广告法》《消费者权益保护法》《食品安全法》等法律法规及各平台运营规则。
请对用户提交的广告物料进行合规审核，输出严格 JSON 格式的审核报告，不得包含任何 JSON 以外的文字。

输出 JSON 结构：
{
  "预审_风险等级": "高" | "中" | "低" | "无明显风险",
  "预审_命中要点": "一句话概括最核心的合规风险",
  "预审_修改建议": "给运营人员的简明修改建议（100字以内）",
  "审核_审核意见": "完整六段式审核报告：①风险定性 ②违禁词鉴别 ③违规类型 ④法律依据 ⑤修改建议 ⑥风险定级",
  "审核_关键实体抽取": "品牌名、产品名、功效词、平台名（逗号分隔）",
  "审核_高风险词命中": "命中的违禁词或高风险词（逗号分隔，无则填'无'）",
  "审核_平台规则预检": "投放平台相关规则命中情况（一句话）",
  "审核_备案核查结果": "MVP阶段暂未接入备案核查，仅根据运营提交字段做形式提示。",
  "审核_推荐违规类型": ["违规类型1", "违规类型2"],
  "审核_推荐风险等级": "高" | "中" | "低",
  "routing": "运营" | "法务"
}

routing 字段判断标准：
- "运营"：违规类型明确、可直接改写，无需法务解释
- "法务"：需要法律解释、存在模糊地带、或涉及重大合规风险"""

    user_message = f"{material_text}\n\n{rules_text}{corrections_text}"

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



def _clean_hit_points(raw: str) -> str:
    """去掉规则引擎暴露的原始 regex:(...) 表达式，只保留字面关键词。支持顿号和逗号分隔。"""
    if not raw:
        return raw
    sep = next((c for c in ['、', '，', ','] if c in raw), '、')
    parts = [p.strip() for p in raw.split(sep)]
    cleaned = [p for p in parts if p and not p.startswith('regex:')]
    return sep.join(cleaned) if cleaned else raw


def _trim_hit_points(raw: str) -> str:
    """
    命中要点字段截断处理：
    规则引擎有时把完整规则明细塞进命中要点，这里只保留第一句概括（分号前）。
    规则明细已在 审核_审核意见 里完整展示，命中要点只需一句话。
    """
    if not raw:
        return raw
    # 取第一个分号/换行前的内容
    for sep in ['；', '\n', ';']:
        idx = raw.find(sep)
        if idx > 0:
            return raw[:idx].strip()
    # 超过80字也截断，加省略号
    if len(raw) > 80:
        return raw[:80].strip() + "…"
    return raw


def _clean_match_reason(raw: str) -> str:
    """去掉 match_reason 中的 regex:... 表达式和前置乱码字符（\ufffd 显示为 ?）。"""
    if not raw:
        return raw
    # 去掉 regex: 及其之后的所有内容（规则引擎通常把正则表达式附在尾部）
    cleaned = re.sub(r'\s*regex:.*', '', raw, flags=re.DOTALL).rstrip()
    # 去掉前置连续乱码字符（Unicode 替换字符 \ufffd 或字面问号）
    cleaned = re.sub(r'^[\ufffd?]+', '', cleaned).strip()
    return cleaned if cleaned else raw


def write_back(record_id: str, llm_result: dict, routing: str, mode: str = "标准"):
    """
    把审核结果回写到多维表格 ②③ 段，更新流转状态。
    llm_result 可来自本地 LLM 或队友规则引擎（字段 key 相同）。
    """
    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    # 规则引擎若返回 audit_time，优先使用；否则用当前时间
    audit_ts = llm_result.get("audit_time") or now_ms

    # 审核意见：规则引擎返回的 审核_审核意见 已包含命中规则明细，直接使用，不再追加
    audit_opinion = llm_result.get("审核_审核意见", "")

    fields = {
        # ② AI预审段（运营可见）
        F_预审_风险等级:      llm_result.get("预审_风险等级", ""),
        F_预审_命中要点:      _trim_hit_points(_clean_hit_points(llm_result.get("预审_命中要点", ""))),
        F_预审_修改建议:      llm_result.get("预审_修改建议", ""),
        F_预审_时间:          audit_ts,
        # ③ AI审核段（法务可见）
        # resolved_mode 优先于运营点选的 mode（规则引擎 MVP 阶段统一返回"标准"）
        F_审核_审核模式:      llm_result.get("resolved_mode", mode),
        F_审核_模式推荐理由:  llm_result.get("mode_reason", "（待分配依据上线后自动填写）"),
        F_审核_审核意见:      audit_opinion,
        F_审核_关键实体抽取:  llm_result.get("审核_关键实体抽取", ""),
        F_审核_高风险词命中:  _clean_hit_points(llm_result.get("审核_高风险词命中", "")),
        F_审核_平台规则预检:  llm_result.get("审核_平台规则预检", ""),
        F_审核_备案核查结果:  llm_result.get(
            "审核_备案核查结果",
            "MVP阶段暂未接入备案核查，仅根据运营提交字段做形式提示。"
        ),
        F_审核_推荐违规类型:  llm_result.get("审核_推荐违规类型", []),
        F_审核_推荐风险等级:  llm_result.get("审核_推荐风险等级", ""),
        F_审核_审核时间:      audit_ts,
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

    兼容两种规则引擎返回格式：
    - 返回 list（命中规则列表）：飞书侧继续调 LLM 生成完整报告（当前占位实现）
    - 返回 dict（含 routing 的完整审核结果）：直接使用，跳过 LLM（队友 API 接入后生效）
    """
    print(f"[predictor] 正式审核开始 record_id={record_id} mode={mode}")

    # 优先从缓存取上下文，避免重复请求
    ctx = _ctx_cache.pop(record_id, None)
    if ctx is None:
        print(f"[predictor] 缓存未命中，重新拉取上下文")
        ctx = build_context(record_id)

    # 保底：若内容仍为空（图片物料 OCR 未完成或写回延迟），强制重跑一次
    if not ctx["content"].strip():
        print(f"[predictor] ⚠ content 为空，强制重跑 OCR")
        from ocr_preprocessor import extract_text_from_attachments
        rec = get_record(record_id)
        fields = rec.get("fields", {})
        ocr_text = extract_text_from_attachments(record_id, fields)
        if ocr_text:
            ctx["content"] = ocr_text
            print(f"[predictor] OCR 补救成功，内容 {len(ocr_text)} 字")
        else:
            raise ValueError("物料内容为空：既无文字也无可识别的图片，无法审核")

    # 调用队友规则引擎
    engine_result = call_teammate_engine(ctx, mode)

    if isinstance(engine_result, dict) and engine_result.get("routing"):
        # 队友引擎返回了完整结果，直接使用，跳过本地 LLM
        print(f"[predictor] 规则引擎返回完整结果，跳过 LLM")
        llm_result = engine_result
        routing = _decide_routing([], llm_result.get("routing", ""))
    else:
        # 当前占位：引擎返回命中列表（或空列表），交给 LLM 生成报告
        hits = engine_result if isinstance(engine_result, list) else []
        print(f"[predictor] 规则引擎命中 {len(hits)} 条，调用 LLM 生成报告")
        llm_result = call_llm(ctx, hits, mode)
        routing = _decide_routing(hits, llm_result.get("routing", ""))

    write_back(record_id, llm_result, routing, mode)
    print(f"[predictor] 审核完成，routing={routing}")
    return routing, llm_result
