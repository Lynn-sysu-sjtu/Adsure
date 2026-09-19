"""高危 IP 实体库 schema（实施方案 v2 第五节）。

library_type 现在就要支持两种来源，哪怕本期只实现 high_risk_public：
  - high_risk_public：平台维护的高危库（维权最活跃的权利主体）
  - customer_owned：  客户自有 IP 库（二期，品牌方查自己的形象被盗用）
两种库共用同一套检索代码，只是来源不同。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LibraryType = Literal["high_risk_public", "customer_owned"]
RiskLevel = Literal["high", "medium", "low"]


class IPLibraryEntry(BaseModel):
    ip_id: str = Field(..., min_length=1)
    name_cn: str
    name_en: str | None = None
    aliases: list[str] = Field(default_factory=list)
    """VLM 用自然语言报名字时的兜底匹配依据。"""

    rights_holder: str
    library_type: LibraryType = "high_risk_public"
    law_ref: list[str] = Field(..., min_length=1)
    required_materials: list[str] = Field(..., min_length=1)
    """命中后要运营补的材料。系统输出的是材料清单，不是侵权结论。"""

    reference_images: list[str] = Field(default_factory=list)
    """相对库根目录的参考图路径（如 disney/mickey_001.jpg）。图可不入库，
    但 SSCD 特征索引必须与这里的条目对应。"""

    risk: RiskLevel = "high"
    enabled: bool = True
    note_to_legal: str | None = None
    """给法务的备注（权属争议、公有领域边界等），不进报告。"""


class IPLibraryMeta(BaseModel):
    name: str
    version: str
    reviewed_by_legal: bool = False
    """法务未复核的库只能用于工程联调，不得用于对外报告。"""


class IPLibrary(BaseModel):
    meta: IPLibraryMeta
    entries: list[IPLibraryEntry]

    def enabled_entries(self) -> list[IPLibraryEntry]:
        return [e for e in self.entries if e.enabled]

    def get(self, ip_id: str) -> IPLibraryEntry | None:
        for e in self.entries:
            if e.ip_id == ip_id:
                return e
        return None

    def match_by_name(self, name: str) -> IPLibraryEntry | None:
        """VLM 没填 ip_id 时按中英文名/别名做精确（归一化后）匹配。

        刻意不做模糊包含匹配：「米老鼠玩偶风挂饰」这类描述不该被当成米奇命中。
        """
        norm = _normalize(name)
        if not norm:
            return None
        for e in self.entries:
            names = [e.name_cn, *( [e.name_en] if e.name_en else [] ), *e.aliases]
            if norm in {_normalize(n) for n in names}:
                return e
        return None


def _normalize(s: str) -> str:
    return "".join((s or "").lower().split())
