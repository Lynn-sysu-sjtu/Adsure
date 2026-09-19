"""类案检索：为涵摄推理提供相似监管实践参照。

三条来自案例库项目约定（AGENTS.md）的硬约束，必须在代码里守住：

  ① **类案只用于规则理解，不等同于产品事实核验。**
     别的公司被罚过，不构成本案的事实认定。类案进 prompt 时
     必须显式标注「仅供参照，不得作为本案事实依据」。

  ② **已核验与待核验必须区分。** 133 条里只有 13 条 review_status=approved。
     把一条未核验的候选案例当成既定判例写进法律报告，是实打实的风险。

  ③ **必须保留 source_url。** 法务要能回溯原文。无出处的案例可以参与
     检索排序，但不该被当作可引用的依据呈现。

检索策略：**直接链接优先于相似度检索**。
L2 词库的每个词条都带着 `cases: [...]` —— 那是挖词时记录的、
「这个词就是在这些案子里被罚的」，比任何相似度算法都准。
相似度检索只在没有直接链接时兜底。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ROOTS = (
    Path(__file__).resolve().parents[3] / "data" / "structured",
    Path(__file__).resolve().parents[3] / "data" / "structured_candidates",
)

# 案例库的行业字段写法不统一，归一到本项目的赛道标识
_SECTOR_PATTERNS = {
    "health_food": ("保健食品", "保健品", "普通食品", "健康产品", "食品"),
    "cosmetics": ("化妆品", "美妆", "医疗美容", "医美"),
    "game": ("游戏",),
}


def _sector_of(industry: str) -> str | None:
    for sector, pats in _SECTOR_PATTERNS.items():
        if any(p in (industry or "") for p in pats):
            return sector
    return None


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    industry: str
    sector: str | None
    penalty_authority: str
    penalty_amount: int | None
    illegal_claims: tuple[str, ...]
    legal_basis: tuple[str, ...]
    mapped_rule_ids: tuple[str, ...]
    keywords: tuple[str, ...]
    vector_text: str
    regulatory_logic: str
    source_url: str
    review_status: str

    @property
    def verified(self) -> bool:
        """已核验且有出处，才够格作为可引用的依据呈现。"""
        return self.review_status == "approved" and bool(self.source_url)

    @property
    def penalty_text(self) -> str:
        if not self.penalty_amount:
            return ""
        return f"罚款 {self.penalty_amount / 10000:.1f} 万元"

    def citation(self) -> str:
        """一行式引用。未核验的必须带标记，不能混在既定判例里。"""
        bits = [self.title or self.case_id]
        if self.penalty_authority:
            bits.append(self.penalty_authority)
        if self.penalty_text:
            bits.append(self.penalty_text)
        line = "；".join(bits)
        return line if self.verified else f"{line}（待核验，仅供线索参考）"


@dataclass
class ScoredCase:
    case: Case
    score: float
    reason: str = ""


@dataclass
class CaseLibrary:
    cases: dict[str, Case] = field(default_factory=dict)

    # ── 加载 ──────────────────────────────────────────────────

    @classmethod
    def load(cls, roots: tuple[Path, ...] | None = None) -> CaseLibrary:
        lib = cls()
        for root in roots or DEFAULT_ROOTS:
            if not root.is_dir():
                continue
            for p in sorted(root.glob("*.json")):
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("跳过无法解析的案例 %s：%s", p.name, exc)
                    continue
                cid = raw.get("case_id")
                if not cid:
                    continue
                industry = raw.get("industry") or ""
                lib.cases[cid] = Case(
                    case_id=cid,
                    title=raw.get("title") or "",
                    industry=industry,
                    sector=_sector_of(industry),
                    penalty_authority=raw.get("penalty_authority") or "",
                    penalty_amount=raw.get("penalty_amount"),
                    illegal_claims=tuple(raw.get("illegal_claims") or []),
                    legal_basis=tuple(raw.get("legal_basis") or []),
                    mapped_rule_ids=tuple(raw.get("mapped_rule_ids") or []),
                    keywords=tuple(raw.get("keywords") or []),
                    vector_text=raw.get("vector_text") or "",
                    regulatory_logic=raw.get("regulatory_logic") or "",
                    source_url=raw.get("source_url") or "",
                    review_status=raw.get("review_status") or "",
                )
        if lib.cases:
            verified = sum(1 for c in lib.cases.values() if c.verified)
            logger.info("类案库载入 %d 条（已核验 %d 条）", len(lib.cases), verified)
        return lib

    @property
    def available(self) -> bool:
        return bool(self.cases)

    def by_id(self, case_id: str) -> Case | None:
        return self.cases.get(case_id)

    # ── 检索 ──────────────────────────────────────────────────

    def retrieve(
        self,
        *,
        term: str = "",
        rule_id: str = "",
        industry: str | None = None,
        linked_case_ids: tuple[str, ...] = (),
        limit: int = 3,
    ) -> list[ScoredCase]:
        """检索相似类案。

        直接链接的案例（词库挖词时记录的出处）一律排在最前 ——
        那是「这个词就是在这些案子里被罚的」，
        比任何基于文本相似度的召回都准。
        """
        scored: dict[str, ScoredCase] = {}

        for cid in linked_case_ids:
            case = self.cases.get(cid)
            if case is not None:
                scored[cid] = ScoredCase(case, 100.0, f"词库直接关联：该表述在本案中被处罚")

        for cid, case in self.cases.items():
            if cid in scored:
                continue
            score, reasons = 0.0, []

            if rule_id and rule_id in case.mapped_rule_ids:
                score += 30
                reasons.append("适用同一法条")
            if industry and case.sector == industry:
                score += 10
                reasons.append("同赛道")
            if term:
                if any(term in c for c in case.illegal_claims):
                    score += 25
                    reasons.append("违规宣称中出现同一表述")
                elif term in case.vector_text or any(term in k for k in case.keywords):
                    score += 8
                    reasons.append("案情描述涉及该表述")

            # ⚠️ 已核验只是**相关案例之间**的排序加分，不能成为召回的理由。
            # 早先无条件加分，结果毫不相关的案例只因为「已核验」就被召回，
            # 报告里会冒出跟本案没关系的类案 —— 那比不给类案更糟。
            if score <= 0:
                continue
            if case.verified:
                score += 5

            scored[cid] = ScoredCase(case, score, "、".join(reasons))

        out = sorted(scored.values(), key=lambda s: (-s.score, s.case.case_id))
        return out[:limit]

    def format_for_prompt(self, results: list[ScoredCase]) -> list[str]:
        """转成喂给大模型的行。刻意只给监管认定逻辑，不给案件细节 ——
        细节会诱导模型把别案事实当成本案事实。"""
        lines = []
        for s in results:
            logic = s.case.regulatory_logic or s.case.vector_text
            lines.append(f"{s.case.citation()}｜监管认定：{logic[:110]}")
        return lines


_LIBRARY: CaseLibrary | None = None


def get_case_library() -> CaseLibrary:
    """进程内缓存。133 个小 JSON，加载一次就够。"""
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = CaseLibrary.load()
    return _LIBRARY
