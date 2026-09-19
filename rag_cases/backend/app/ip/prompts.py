# -*- coding: utf-8 -*-
"""VLM IP 巡检的结构化 prompt（方案 §5 三重防线之二）。

防线设计：
  ① 底库优先，VLM 只兜底（detector 的调用顺序保证）
  ② prompt 必须提供「无 / 不确定」选项，不逼模型二选一 —— 本文件
  ③ 仅 VLM 命中一律「疑似待确认」，不进正式清单 —— detector 融合层强制
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是广告画面 IP 元素核查员。只做视觉事实描述，不做侵权认定。

任务：检查给定广告帧中是否出现受保护的知名 IP 形象、品牌 logo、名人肖像。
必须遵守：
1. 只能报告你有把握的、具体可名的知名 IP（如米奇、皮卡丘、Hello Kitty）。
2. 「原创/通用卡通形象」「风格相似但说不上是谁」一律不算命中。
3. 每一批图片你必须给出明确结论；没有发现时返回空数组，不确定时 uncertainty=true。
4. 严禁根据玩具、贴纸、周边商品的描述推断 IP；只看画面里实际绘制/出现的形象。
5. 只输出 JSON，不要输出任何解释性文字。JSON 格式：
{
  "uncertainty": false,
  "entities": [
    {
      "frame_index": 0,
      "ip_id": "disney_mickey 或在你确信但清单无对应时填 null",
      "name_cn": "你认为的具体名字，不确定就不要输出该条",
      "entity_type": "cartoon_character | brand_logo | celebrity | artwork | architecture | other",
      "bbox": [x, y, w, h],
      "confidence": 0.0
    }
  ]
}
bbox 为归一化坐标（左上原点，w/h ≤ 1）。没有任何发现时返回
{"uncertainty": false, "entities": []}。
整体看不准时 uncertainty 置 true，entities 仍可列出你最有把握的候选。"""


def build_scan_prompt(n_frames: int) -> str:
    return f"以下是 {n_frames} 帧广告画面（按输入顺序，frame_index 从 0 起）。请逐帧检查。"


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_vlm_response(text: str) -> tuple[list[dict], bool]:
    """解析 VLM 返回。坏 JSON / 越界字段一律按「无可靠结果」处理。

    宁可漏（底库与下一条视频还会兜）也不可凭半句话造出一条 IP 误报 ——
    IP 误报会让法务白跑一趟要授权书，信任崩一次就回不来。
    """
    if not text:
        return [], True
    m = _JSON_RE.search(text)
    if not m:
        logger.warning("VLM 返回中找不到 JSON，按无结果处理：%.80s", text)
        return [], True
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("VLM 返回 JSON 不可解析，按无结果处理：%.80s", text)
        return [], True

    raw_entities = data.get("entities") if isinstance(data, dict) else None
    uncertainty = bool(isinstance(data, dict) and data.get("uncertainty"))
    if not isinstance(raw_entities, list):
        return [], True

    entities: list[dict] = []
    valid_types = {
        "cartoon_character", "brand_logo", "celebrity",
        "artwork", "architecture", "other",
    }
    for i, e in enumerate(raw_entities):
        if not isinstance(e, dict):
            continue
        name = str(e.get("name_cn") or "").strip()
        etype = e.get("entity_type")
        bbox = e.get("bbox")
        fi = e.get("frame_index")
        if not name or etype not in valid_types:
            continue
        if not isinstance(fi, int) or fi < 0 or fi >= 10_000:
            continue
        ok_bbox = (
            isinstance(bbox, list) and len(bbox) == 4
            and all(isinstance(v, (int, float)) for v in bbox)
            and 0 <= bbox[0] <= 1 and 0 <= bbox[1] <= 1
            and 0 < bbox[2] <= 1 and 0 < bbox[3] <= 1
            and bbox[0] + bbox[2] <= 1 + 1e-6 and bbox[1] + bbox[3] <= 1 + 1e-6
        )
        conf = e.get("confidence", 0.0)
        conf = conf if isinstance(conf, (int, float)) and 0 <= conf <= 1 else 0.0
        ip_id = e.get("ip_id")
        entities.append({
            "frame_index": fi,
            "ip_id": ip_id if isinstance(ip_id, str) and ip_id.strip() else None,
            "name_cn": name,
            "entity_type": etype,
            "bbox": tuple(bbox) if ok_bbox else None,
            "confidence": conf,
        })
    return entities, uncertainty
