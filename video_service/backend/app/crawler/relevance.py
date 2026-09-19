"""案例与广告合规的相关性判定 —— 逐段判，不逐篇判。

标题级过滤挡不住混编通报：「守护消费铁拳行动典型案例」一篇里既有违法广告，
也有电子秤作弊、计量器具、不合格产品。实测抓回的 80 条里 37% 属于后者 ——
它们是真实、可溯源的处罚案例，只是**对广告合规没用**，
却会照样占满人工复核产能。

所以这里只做**标注**，不做删除：
  · 删掉等于替人做了取舍，而这些案例对别的用途仍有价值；
  · 不标注则等于把筛选成本转嫁给复核的人，一条条读标题去挑。

判定是纯规则的、可复现的，不调模型 —— 相关性判断错了顶多排错序，
不值得为它花模型钱，更不该引入一个没法解释的分数。
"""

from __future__ import annotations

import re
from enum import StrEnum

# 广告合规的核心动作：发布广告、宣传、代言、直播带货
#
# ⚠️「在广告中宣称X」是本项目最典型的案由，必须在这一档 ——
# 只列「违法广告」「广告主」这类名词会漏掉它，落到 MAYBE，
# 而 MAYBE 在复核队列里是靠后的，等于把正题排到了后面。
_CORE = re.compile(r"违法广告|广告主|广告经营者|广告经营|广告发布者|广告代言|代言人"
                   r"|发布.{0,6}广告|广告中(?:宣称|声称|使用|含有|出现)"
                   r"|广告语|广告内容|广告费"
                   r"|虚假宣传|引人误解|夸大宣传|误导性|商业宣传"
                   r"|直播带货|带货|种草|软文|推广费")

# 与广告相关但也可能出现在别的语境（如「宣传册」只是载体）
_WEAK = re.compile(r"广告|宣传|直播|营销|推销|推介|网红|主播|种草")

# 明确属于别的监管条线 —— 命中这些且没命中 _CORE，基本可以判为不相关
_OTHER_TRACK = re.compile(
    r"计量器具|电子秤|电子天平|加油机|作弊装置|破坏计量"
    r"|不合格|以假充真|以次充好|伪劣|强制性国家标准|质量不合格"
    r"|注册商标专用权|侵犯商标|专利侵权"
    r"|合同条款|格式条款|价格违法|明码标价"
    r"|检验检测报告|检测报告|鉴定证书"
    r"|食品添加剂|添加药品|食品安全标准|经营添加"
)


class Relevance(StrEnum):
    AD = "ad"                 # 广告/宣传违法，本项目的正题
    MAYBE = "maybe"           # 提到广告相关词，但主线可能在别处
    OTHER_TRACK = "other"     # 明确属于别的监管条线


def ad_relevance(*parts: str | None) -> Relevance:
    """判定相关性。传入标题、事实摘要、违法表述等任意片段。

    判定顺序是刻意的：**先看有没有广告合规的核心动作，再看别的条线**。
    反过来会把「在广告中宣称产品不含防腐剂（实为不合格产品）」判成质量案 ——
    那种案子恰恰是本项目要的，违法性在「广告里怎么说」，不在产品本身。
    """
    text = "".join(p or "" for p in parts)
    if not text:
        return Relevance.MAYBE
    if _CORE.search(text):
        return Relevance.AD
    if _OTHER_TRACK.search(text):
        return Relevance.OTHER_TRACK
    if _WEAK.search(text):
        return Relevance.MAYBE
    return Relevance.OTHER_TRACK


def tag_case(case: dict, segment_text: str = "") -> dict:
    """给案例打上相关性标签，就地修改并返回。"""
    claims = case.get("illegal_claims") or []
    case["topic_relevance"] = ad_relevance(
        case.get("segment_title"),
        case.get("title"),
        case.get("facts_summary"),
        " ".join(map(str, claims)) if isinstance(claims, list) else str(claims),
        segment_text,
    ).value
    return case
