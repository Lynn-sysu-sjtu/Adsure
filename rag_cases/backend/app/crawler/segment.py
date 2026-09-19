"""把一个页面拆成多个案例。

**这是看了真实页面才发现必须有的一层。**

市监总局的典型案例通报是「一篇文章 = 七起案例」：正文以「一、二、三……」
分节，每节是一个独立案子（各有当事人、处罚机关、法条、金额）。
按「一个 URL 一个案例」处理会把七个案子揉成一条，
抽出来的金额和当事人全是错位的 —— 而且不会报错。

拆分后每个案例共享同一个 source_url 与 raw_text_path，
各自有独立 case_id 与 segment_index，回溯时能定位到原文的哪一节。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 「一、xxx案」这种小节标题。要求顶格且后接顿号，避免命中正文里的「一、二线城市」
_SECTION = re.compile(
    r"^[ \t]*(?:([一二三四五六七八九十百]+)[、．.]|案例[一二三四五六七八九十百]+[：:])\s*(\S.{4,120})$",
    re.M,
)

# 太短的片段不可能是一个完整案例，多半是目录或导语被误切
_MIN_SEGMENT_CHARS = 120


@dataclass
class Segment:
    index: int
    title: str
    text: str

    @property
    def suffix(self) -> str:
        return f"_{self.index:02d}"


def split_cases(text: str, min_chars: int = _MIN_SEGMENT_CHARS) -> list[Segment]:
    """按中文序号小节拆分。拆不出就整篇作为一个案例返回。

    拆不出时返回整篇而不是空列表 —— 地方局的单案公示本来就没有分节，
    那种页面一篇就是一个案子，是正常情况不是失败。
    """
    matches = list(_SECTION.finditer(text or ""))
    if len(matches) < 2:
        return [Segment(0, "", text)] if (text or "").strip() else []

    segments: list[Segment] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start():end].strip()
        if len(body) < min_chars:
            logger.debug("片段「%s」仅 %d 字，疑似目录项，跳过", m.group(2)[:20], len(body))
            continue
        segments.append(Segment(len(segments) + 1, m.group(2).strip(), body))

    if not segments:
        # 找到了小节标题却一个都没通过长度门槛 —— 可能是目录页，
        # 也可能是 min_chars 设得过高把真案例滤掉了。
        # 静默退回整页会让后者变成「七个案子揉成一条」且无人察觉，所以要告警。
        logger.warning(
            "识别到 %d 个小节标题但全部短于 %d 字，已退回整页处理。"
            "若该页确实含多个案例，说明长度门槛过高，需下调。",
            len(matches), min_chars,
        )
        return [Segment(0, "", text)]

    logger.info("页面拆出 %d 个案例小节", len(segments))
    return segments
