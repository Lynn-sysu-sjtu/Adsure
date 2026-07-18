# -*- coding: utf-8 -*-
"""
召回向量层 · 最小实现（Demo / Mock）
=====================================
不依赖外部 embedding 模型，用字符 n-gram + 余弦相似度模拟语义召回。

设计：两路并进召回
  ① 确定性召回：关键词匹配 + 正则（原 demo.py 已有）
  ② 语义召回  ：对每条规则的 recall.vector_text 建 n-gram 向量，与文案做余弦相似度

对外暴露：
  combined_recall(text, keyword_recall_fn) → List[CandidateDict]
  recall_by_vector(text, top_k, threshold) → List[VectorHitDict]
"""

import json
import math
import re
from collections import Counter

RULES_FN = "三赛道广告合规规则库_v0.4_首批高频规则样例.json"

with open(RULES_FN, "r", encoding="utf-8") as f:
    _lib = json.load(f)

rules = _lib["rules"]


# ─────────────────────────────────────────────────────────────
# 工具函数：字符 n-gram 分词
# ─────────────────────────────────────────────────────────────

def _ngrams(text: str, ns=(1, 2, 3)) -> list:
    text = re.sub(r"\s+", "", text)
    tokens = []
    for n in ns:
        for i in range(len(text) - n + 1):
            tokens.append(text[i : i + n])
    return tokens


def _tf_vector(tokens: list) -> dict:
    cnt = Counter(tokens)
    total = sum(cnt.values()) or 1
    return {k: v / total for k, v in cnt.items()}


def _cosine(v1: dict, v2: dict) -> float:
    common = set(v1) & set(v2)
    if not common:
        return 0.0
    dot = sum(v1[k] * v2[k] for k in common)
    n1 = math.sqrt(sum(x * x for x in v1.values()))
    n2 = math.sqrt(sum(x * x for x in v2.values()))
    return dot / (n1 * n2) if n1 and n2 else 0.0


# ─────────────────────────────────────────────────────────────
# 预计算：规则向量索引
# ─────────────────────────────────────────────────────────────

_rule_index = []
for _r in rules:
    _rec = _r.get("recall", {})
    _vt = _rec.get("vector_text", "")
    _tags = _rec.get("tags", [])
    _combined = _vt + " " + " ".join(_tags)
    _rule_index.append({
        "rule": _r,
        "vector": _tf_vector(_ngrams(_combined)),
        "tags": _tags,
        "vector_text": _vt,
    })


# ─────────────────────────────────────────────────────────────
# 语义召回：向量相似度
# ─────────────────────────────────────────────────────────────

def recall_by_vector(text: str, top_k: int = 3, threshold: float = 0.06) -> list:
    """
    返回余弦相似度 >= threshold 的 top_k 条规则。
    每项结构：{"rule": ..., "score": float, "tags": [...], "recall_type": "semantic"}
    """
    qv = _tf_vector(_ngrams(text))
    scored = []
    for ri in _rule_index:
        s = _cosine(qv, ri["vector"])
        scored.append((s, ri))
    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, ri in scored[:top_k]:
        if score >= threshold:
            results.append({
                "rule": ri["rule"],
                "score": round(score, 4),
                "tags": ri["tags"],
                "recall_type": "semantic",
            })
    return results


# ─────────────────────────────────────────────────────────────
# 并进召回：确定性 + 语义 合并
# ─────────────────────────────────────────────────────────────

def combined_recall(
    text: str,
    keyword_recall_fn,
    top_k_vector: int = 2,
    threshold: float = 0.06,
) -> list:
    """
    两路并进召回，返回去重合并后的候选列表。

    每项结构：
      {
        "rule": <规则对象>,
        "hits": [<命中信号字符串>, ...],   # 确定性：命中词/正则；语义：[语义召回 score=x.xx]
        "recall_type": "deterministic" | "semantic" | "both"
      }

    用法（在 demo.py 中替换原 recall 调用）：
      from recall_vector import combined_recall
      cands = combined_recall(text, keyword_recall_fn=recall)
    """
    # ① 确定性召回
    det = keyword_recall_fn(text)
    det_map = {}
    for c in det:
        rid = c["rule"]["rule_id"]
        det_map[rid] = {
            "rule": c["rule"],
            "hits": c.get("hits", []),
            "recall_type": "deterministic",
        }

    # ② 语义召回
    vec = recall_by_vector(text, top_k=top_k_vector, threshold=threshold)
    vec_map = {}
    for v in vec:
        rid = v["rule"]["rule_id"]
        vec_map[rid] = v

    # ③ 合并去重
    merged = {}
    for rid, c in det_map.items():
        merged[rid] = c
    for rid, v in vec_map.items():
        if rid in merged:
            # 两路都命中
            merged[rid]["recall_type"] = "both"
            merged[rid]["hits"].append(f"[语义召回 score={v['score']}]")
        else:
            merged[rid] = {
                "rule": v["rule"],
                "hits": [f"[语义召回 score={v['score']}]"],
                "recall_type": "semantic",
            }

    return list(merged.values())


# ─────────────────────────────────────────────────────────────
# 快速调试入口
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    samples = [
        "全球销量第一的抗衰精华，效果最好，7天淡纹立刻见效。",
        "纯中药配方，3天消炎祛痘不留印，治疗青春痘痤疮。",
        "【亲测】这款精华太好用了，无限回购！（附商品链接）",
        "某品牌美白面膜，一片见效，肤色提亮2个色号。",
        "普通保湿面霜，温和舒缓，日常护理。",
    ]

    from demo import recall as keyword_recall  # 借用 demo 里的关键词召回

    print("=" * 60)
    for txt in samples:
        print(f"\n【文案】{txt}")
        cands = combined_recall(txt, keyword_recall)
        if not cands:
            print("  → 未召回任何规则")
        for c in cands:
            icon = {"deterministic": "🔑", "semantic": "🔍", "both": "🔑🔍"}.get(
                c["recall_type"], "?"
            )
            print(f"  {icon} [{c['recall_type']}] {c['rule']['rule_id']}: {c['rule']['title']}")
            print(f"     hits: {c['hits']}")

