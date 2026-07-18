"""
轻量规则沉淀 — Few-shot 注入系统

存储法务纠正记录（refine/override）到本地 JSON。
检索时对物料内容做 bigram 重叠召回，返回 top-3 相关历史纠正，
拼入 LLM prompt，实现AI从法务反馈中学习效果。
"""
import json
import uuid
import datetime
from pathlib import Path

CORRECTIONS_PATH = Path(__file__).parent / "data" / "corrections.json"


def _load() -> list:
    if not CORRECTIONS_PATH.exists():
        return []
    try:
        return json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(records: list):
    CORRECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORRECTIONS_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_correction(
    record_id: str,
    content_snippet: str,
    industry: str,
    platform: str,
    ai_risk_level: str,
    ai_violation_types: list,
    feedback_type: str,
    objection_fields: list,
    correct_judgment: str,
    reason: str,
) -> dict:
    """保存一条法务纠正记录，返回保存的 entry dict。"""
    records = _load()
    entry = {
        "id":                 str(uuid.uuid4())[:8],
        "created_at":         datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "record_id":          record_id,
        "industry":           industry,
        "platform":           platform,
        "content_snippet":    content_snippet[:120],
        "ai_risk_level":      ai_risk_level,
        "ai_violation_types": ai_violation_types,
        "feedback_type":      feedback_type,
        "objection_fields":   objection_fields,
        "correct_judgment":   correct_judgment,
        "reason":             reason,
        "status":             "active",
    }
    records.append(entry)
    _save(records)
    print(f"[preference_memory] 已保存纠正记录 id={entry['id']} feedback_type={feedback_type}")
    return entry


def _bigram_overlap(a: str, b: str) -> int:
    """统计两段文字共有的2字词数量（简单相似度）。"""
    if not a or not b:
        return 0
    bg_a = {a[i:i+2] for i in range(len(a) - 1)}
    bg_b = {b[i:i+2] for i in range(len(b) - 1)}
    return len(bg_a & bg_b)


def retrieve_relevant(content: str, industry: str = "", top_k: int = 3) -> list:
    """
    从历史纠正记录中召回最相关的 top_k 条（仅 active）。
    同行业记录优先，再按 bigram 重叠排序。
    """
    records = [r for r in _load() if r.get("status") == "active"]
    if not records:
        return []

    # 严格按行业隔离，不跨行业召回，避免美妆/游戏/保健食品规则互相污染
    pool = [r for r in records if r.get("industry") == industry]
    if not pool:
        return []

    scored = [(r, _bigram_overlap(content, r.get("content_snippet", ""))) for r in pool]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [r for r, score in scored[:top_k] if score > 0]


def format_for_prompt(corrections: list) -> str:
    """把召回案例格式化为 LLM prompt 文本块。"""
    if not corrections:
        return ""
    lines = ["\n【法务历史纠正案例 — 请严格参考以下案例，避免重复同类误判】"]
    for i, c in enumerate(corrections, 1):
        label = "override（AI误判，法务驳回）" if c["feedback_type"] == "override" else "refine（AI遗漏，法务补充）"
        lines.append(
            f"\n案例 {i}【{label}】"
            f"\n  物料片段：{c['content_snippet']}"
            f"\n  AI原判定：风险{c.get('ai_risk_level', '')}·{', '.join(c.get('ai_violation_types', []))}"
            f"\n  法务纠正：{c['correct_judgment']}"
            f"\n  理由：{c['reason']}"
        )
    return "\n".join(lines)


def list_all() -> list:
    """返回全部纠正记录（前端显示用）。"""
    return _load()


def set_status(correction_id: str, status: str) -> bool:
    """切换记录状态（active / paused）。"""
    records = _load()
    for r in records:
        if r.get("id") == correction_id:
            r["status"] = status
            _save(records)
            return True
    return False


def delete_correction(correction_id: str) -> bool:
    """永久删除一条纠正记录。"""
    records = _load()
    new_records = [r for r in records if r.get("id") != correction_id]
    if len(new_records) == len(records):
        return False
    _save(new_records)
    return True
