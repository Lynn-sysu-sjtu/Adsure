# -*- coding: utf-8 -*-
"""裁决回流（实施方案 v2 §15 方向 7、§14 闭环）。

法务在飞书里对每条风险做出裁决后，裁决结果沉淀回三个库：

  1. 规则校准  → data/rules/feedback/lexicon_feedback.jsonl
     误报 → 词库白名单语境或降级建议；漏报 → 新词条建议
  2. 类案补充  → data/rules/feedback/case_feedback.jsonl
     真实处置结果可作为类案库的候选（review_status=pending，需人工核验后才能引用）
  3. IP 底库   → data/rules/feedback/ip_feedback.jsonl
     VLM 疑似命中的确认/否决 → 底库增删参考图的依据

设计原则（与 AGENTS.md 一致）：
  - 裁决是**人工事实**，系统只做忠实记录，不改写、不推断
  - 回流数据一律 append-only JSONL，不覆盖历史
  - 每条带 job_id + finding 定位（t_start/bbox）+ 裁决人，可回溯到原始证据
  - **不自动生效**：词库/阈值修改必须经人工应用（apply 脚本生成 diff 供 review），
    防止一条错误裁决污染整个词库
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

FEEDBACK_ROOT = Path(__file__).resolve().parents[2] / "data" / "rules" / "feedback"

# 裁决动作 → 回流去向
Adjudication = Literal[
    "confirmed_violation",   # 确认违规：→ 类案候选 + 词库增强（词条已有则记案例）
    "false_positive",        # 误报：→ 词库白名单/降级建议
    "missed_risk",           # 漏报：→ 新词条建议
    "not_applicable",        # 不适用：→ 词库豁免语境建议
    "needs_more_evidence",   # 材料不足待补：仅记录，不进词库
    "ip_confirmed",          # IP 命中确认：→ IP 底库参考图收集依据
    "ip_rejected",           # IP 误报否决：→ VLM 负样本 / 底库排除依据
]


class AdjudicationRecord(BaseModel):
    """一条法务裁决。字段设计对齐飞书卡片可回传的信息。"""

    job_id: str
    finding_index: int = Field(ge=0)
    """对应 report.json findings 数组的下标。"""

    title: str
    """裁决时的风险标题（冗余存一份，防止报告重新生成后对不上）。"""

    t_start: float = 0.0
    t_end: float = 0.0
    source: str = ""
    """口播 / 画面文字 / 全片 —— 决定回流到 ASR 词库还是 OCR 词库。"""

    action: Adjudication
    reason: str = ""
    """法务填写的裁决理由。误报理由尤其重要——它就是白名单语境的原始素材。"""

    adjudicator: str = ""
    adjudicated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # 可选定位信息（IP 类裁决用）
    ip_id: str | None = None
    entity_name: str | None = None

    # 原始命中上下文（误报分析用，从报告带过来）
    matched_text: str = ""
    context: str = ""

    @property
    def feedback_kind(self) -> Literal["lexicon", "case", "ip"]:
        if self.action in {"ip_confirmed", "ip_rejected"}:
            return "ip"
        if self.action == "confirmed_violation":
            return "case"
        return "lexicon"


def save_adjudication(record: AdjudicationRecord,
                      root: Path | None = None) -> Path:
    """追加一条裁决到对应 JSONL。append-only，不覆盖。"""
    root = Path(root) if root else FEEDBACK_ROOT
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{record.feedback_kind}_feedback.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")
    logger.info("裁决已回流：%s → %s", record.action, path.name)
    return path


def load_feedback(kind: Literal["lexicon", "case", "ip"],
                  root: Path | None = None) -> list[AdjudicationRecord]:
    path = (Path(root) if root else FEEDBACK_ROOT) / f"{kind}_feedback.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(AdjudicationRecord(**json.loads(line)))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("跳过损坏的反馈行：%s", e)
    return out


# ── 词库校准建议生成（人工 review 后应用，不自动改词库）──────────


class LexiconSuggestion(BaseModel):
    """从裁决提炼的词库修改建议。**建议**，不是自动生效的修改。"""

    suggestion_type: Literal[
        "add_whitelist_context",   # 误报 → 给词条加白名单语境
        "downgrade_risk",          # 误报 → 词条降级
        "add_term",                # 漏报 → 新词条（需法务补法条依据）
        "add_exempt_hint",         # 不适用 → 豁免情形提示
    ]
    term: str
    lexicon_layer: Literal["L1", "L2", "L3"]
    industry: str = "*"
    proposal: str
    """具体建议内容（如白名单短语、新词条 YAML 片段）。"""
    evidence_jobs: list[str] = Field(default_factory=list)
    """支撑该建议的 job_id 列表。"""
    reason_count: int = 1
    """同类误报/漏报出现次数——次数越多越该优先处理。"""


def build_lexicon_suggestions(
    records: list[AdjudicationRecord],
) -> list[LexiconSuggestion]:
    """聚合裁决记录 → 去重的词库修改建议。

    同一 matched_text 的多条同类裁决合并为一条建议，计数累加。
    """
    buckets: dict[tuple, LexiconSuggestion] = {}
    for r in records:
        if r.feedback_kind != "lexicon" or not r.matched_text:
            continue
        if r.action == "false_positive":
            st: LexiconSuggestion.suggestion_type = "add_whitelist_context"
            proposal = f"白名单语境候选：{r.context or r.reason}"
        elif r.action == "missed_risk":
            st = "add_term"
            proposal = f"新词条候选：「{r.matched_text}」（{r.reason}）"
        elif r.action == "not_applicable":
            st = "add_exempt_hint"
            proposal = f"豁免情形：{r.reason}"
        else:
            continue
        layer = "L1" if "绝对化" in r.title or any(
            t in r.matched_text for t in ("国家级", "第一", "最")) else "L2"
        key = (st, r.matched_text, layer)
        if key in buckets:
            buckets[key].reason_count += 1
            if r.job_id not in buckets[key].evidence_jobs:
                buckets[key].evidence_jobs.append(r.job_id)
        else:
            buckets[key] = LexiconSuggestion(
                suggestion_type=st, term=r.matched_text, lexicon_layer=layer,
                proposal=proposal, evidence_jobs=[r.job_id])
    return sorted(buckets.values(), key=lambda s: -s.reason_count)


def build_ip_feedback_summary(
    records: list[AdjudicationRecord],
) -> dict[str, dict]:
    """IP 裁决汇总：每个 ip_id/entity 的确认/否决计数 → 底库维护依据。"""
    summary: dict[str, dict] = {}
    for r in records:
        if r.feedback_kind != "ip":
            continue
        key = r.ip_id or f"name:{r.entity_name or 'unknown'}"
        entry = summary.setdefault(key, {
            "ip_id": r.ip_id, "entity_name": r.entity_name,
            "confirmed": 0, "rejected": 0, "jobs": []})
        if r.action == "ip_confirmed":
            entry["confirmed"] += 1
        elif r.action == "ip_rejected":
            entry["rejected"] += 1
        if r.job_id not in entry["jobs"]:
            entry["jobs"].append(r.job_id)
    return summary
