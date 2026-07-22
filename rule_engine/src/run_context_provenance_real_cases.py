"""Run two real DeepSeek + Zhipu rounds for context-provenance acceptance."""

import json
import os
import sys

from audit_api import audit_endpoint


CASES = [
    (
        "game",
        {
            "record_id": "context-provenance-game",
            "mode": "标准",
            "fields": {
                "①运营·行业领域": "游戏",
                "①运营·物料内容": "（图片素材）开局十连抽，爆率拉满，神装随便出",
                "①运营·补充背景资料": "图片素材，买量信息流广告；核心卖点：充值即可获得高爆率装备",
                "①游戏·物料类型": "图文海报",
                "①游戏·产品品类": "网络游戏",
                "①游戏·投放平台": ["抖音", "小红书"],
            },
        },
    ),
    (
        "beauty",
        {
            "record_id": "context-provenance-beauty",
            "mode": "标准",
            "fields": {
                "①运营·行业领域": "美妆",
                "①运营·物料内容": "（图片素材）我们的美白精华一降价你还不是和狗一样跑过来",
                "①运营·补充背景资料": "图片素材，电商大促信息流广告；产品为美白精华液",
                "①美妆·物料类型": "图文海报",
                "①美妆·产品品类": "护肤品",
                "①美妆·投放平台": ["小红书", "抖音"],
                "①美妆·核心宣称功效": "美白",
            },
        },
    ),
    (
        "health",
        {
            "record_id": "context-provenance-health",
            "mode": "标准",
            "fields": {
                "①运营·行业领域": "保健食品",
                "①运营·物料内容": "治疗肝癌、肺癌、结肠癌等 80%-90%癌症病类",
                "①运营·补充背景资料": "产品为普通果汁饮品，非保健食品，无任何批准文号，微信朋友圈推广",
                "①保健食品·物料类型": "图文",
                "①保健食品·产品品类": "果汁饮品",
                "①保健食品·投放平台": ["微信"],
                "①保健食品·核心宣称功效": "治疗癌症",
                "①保健食品·批准文号": "",
            },
        },
    ),
]


def _rule_summary(data):
    return [
        {
            "rule_id": item.get("rule_id"),
            "status": item.get("applicability_status"),
            "industries": (item.get("applies_to") or {}).get("industries") or [],
            "evidence": item.get("material_evidence"),
        }
        for item in data.get("matched_rules", [])
    ]


def _check(name, data):
    rules = data.get("matched_rules", [])
    if name == "game":
        return any(
            item.get("rule_id") == "GAME-FALSE-004"
            and item.get("applicability_status") == "needs_fact_verification"
            for item in rules
        )
    if name == "beauty":
        return (
            data.get("审核_推荐风险等级") == "高"
            and data.get("routing") == "法务"
            and any(
                item.get("rule_id") == "GEN-GOOD-CUSTOMS-001"
                and item.get("applicability_status") == "confirmed_violation"
                for item in rules
            )
        )

    general_medical_confirmed = any(
        item.get("rule_id") == "GEN-MED-001"
        and item.get("applicability_status") == "confirmed_violation"
        for item in rules
    )
    health_specific_confirmed = [
        item.get("rule_id")
        for item in rules
        if item.get("applicability_status") == "confirmed_violation"
        and "保健食品" in ((item.get("applies_to") or {}).get("industries") or [])
        and "通用" not in ((item.get("applies_to") or {}).get("industries") or [])
    ]
    suggestion = data.get("预审_修改建议") or ""
    return (
        general_medical_confirmed
        and not health_specific_confirmed
        and "本品不能代替药物" not in suggestion
    )


def main():
    required = {
        "DEEPSEEK_API_KEY": bool(os.getenv("DEEPSEEK_API_KEY")),
        "ZHIPU_KEY": bool(os.getenv("ZHIPU_API_KEY") or os.getenv("ZHIPUAI_API_KEY")),
    }
    if not all(required.values()):
        print(json.dumps({"configured": required}, ensure_ascii=False, indent=2))
        return 2

    failed = []
    for run in (1, 2):
        print(f"\n{'=' * 72}\nRUN {run}\n{'=' * 72}")
        for name, payload in CASES:
            diagnostics = {}
            response = audit_endpoint(payload, diagnostics=diagnostics)
            data = response.get("data") or {}
            passed = response.get("code") == 0 and _check(name, data)
            result = {
                "case": name,
                "passed": passed,
                "code": response.get("code"),
                "msg": response.get("msg"),
                "risk": data.get("审核_推荐风险等级"),
                "routing": data.get("routing"),
                "rules": _rule_summary(data),
                "suggestion": data.get("预审_修改建议"),
                "diagnostics": diagnostics,
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if not passed:
                failed.append({"run": run, "case": name})

    print(f"\nSUMMARY: {6 - len(failed)}/6 passed")
    if failed:
        print(json.dumps({"failed": failed}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
