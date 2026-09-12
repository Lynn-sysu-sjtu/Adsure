"""Keep platform candidates, production eligibility, and advertising-law results separate."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT/"data/platform_rules/structured_candidates/2026-09-04/beauty_platform_rule_candidates.json"
MAP = {
    "XHS-JG-COSM-EFFECT-2.1.3":{"patterns":["quantified_effect","safety_guarantee"],"industry":"化妆品"},
    "XHS-JG-ABSOLUTE-2.3":{"patterns":["absolute_core","absolute_context"]},
    "XHS-JG-MEDICAL-2.13":{"patterns":["medical_claim"]},
    "XHS-JG-DATA-2.8":{"patterns":["quantified_effect"]},
    "XHS-JG-ENDORSEMENT-2.11":{"patterns":["authority_endorsement"],"scene_categories":["third_party_endorsement"]},
    "XHS-JG-COMPARE-2.15":{"scene_categories":["before_after_comparison"]},
    "XHS-JG-PATENT-1.10":{"terms":["专利"]},
    "XHS-JG-INGREDIENT-2.9":{"terms":["成分","烟酰胺","玻尿酸","维生素"]},
    "XHS-JG-FACT-2.10":{"terms":["临床验证","权威认证","销量"]},
    "XHS-JG-CONSISTENCY-4.4":{"manual":True},
    "XHS-JG-AD-ID-1.11":{"manual":True},
    "DOUYIN-COSM-EFFICACY-2.1.1":{"patterns":["medical_claim"],"terms":["美白","祛斑","防晒"],"industry":"化妆品"},
    "DOUYIN-COSM-GUARANTEE-2.1.2":{"patterns":["safety_guarantee","quantified_effect"],"industry":"化妆品"},
    "DOUYIN-COSM-PROOF-2.3":{"terms":["专利","荣誉","销量","研发","效果指数"],"industry":"化妆品"},
    "DOUYIN-COSM-ATTRIBUTE-2.4":{"manual":True,"industry":"化妆品"},
}


def source_status(rule: dict, today: date) -> dict:
    info={"integrity":"unverified","freshness":"unknown","production_eligible":False}
    try:
        path=(ROOT/rule["raw_text_path"]).resolve()
        if not path.is_relative_to(ROOT/"data/platform_rules"):
            raise ValueError("source path outside rule archive")
        raw=json.loads(path.read_text())
        original=(ROOT/raw["raw_path"]).resolve()
        if not original.is_relative_to(ROOT/"data/platform_rules"):
            raise ValueError("invalid source archive path")
        actual=hashlib.sha256(original.read_bytes()).hexdigest()
        info["integrity"]="matched" if actual==rule["raw_sha256"]==raw["raw_sha256"] else "hash_mismatch"
        collected=date.fromisoformat(raw["collected_at"][:10])
        info["collected_at"]=raw["collected_at"]
        info["page_update_date"]=raw.get("page_update_date")
        info["snapshot_completeness"]=raw.get("snapshot_completeness")
        age=(today-collected).days
        info["freshness"]="recent_capture_not_currently_confirmed" if 0<=age<=30 else "stale_or_invalid"
        if raw.get("page_update_date") and (today-date.fromisoformat(raw["page_update_date"])).days>365:
            info["freshness"]="historical_version_recheck_required"
        info["effective_status"]=rule["effective_status"]
        info["review_status"]=rule["review_status"]
        info["production_eligible"]=(info["integrity"]=="matched" and rule["effective_status"]=="active" and
                                     rule["review_status"]=="approved" and info["freshness"]=="recent_capture_not_currently_confirmed")
    except Exception as exc:
        info["error"]=str(exc)
    return info


def check_platforms(evidence, risks, semantics: dict, *, platform: str, industry: str, product_category: str, landing_page_text="", today=None):
    today=today or date.today()
    result={"status":"manual_review_required","human_review_required":True,"production_ready":False,"platforms":[],"findings":[],
            "warnings":[],"rules_considered":[],"boundary":"平台候选与行政违法认定分开；不得承诺投放通过。"}
    if not platform.strip():
        result["warnings"].append("未选择平台与场景，平台规则未检查")
        return result
    targets=[]
    if "小红书" in platform:
        targets.append("小红书")
    if "抖音电商" in platform:
        targets.append("抖音电商")
    if "抖音" in platform and "抖音电商" not in platform:
        result["warnings"].append("仅写抖音不能确定电商或巨量广告场景；未套用电商规则")
    if not targets:
        result["warnings"].append("所选平台/场景暂无可执行目录")
        return result
    result["platforms"]=targets
    try:
        catalog=json.loads(CATALOG.read_text())
    except (OSError,ValueError):
        result["status"]="rules_unavailable"
        result["warnings"].append("平台规则目录缺失或不可解析，未执行平台核验")
        return result
    for rule in catalog["rules"]:
        selector=MAP.get(rule["candidate_id"])
        if rule["platform"] not in targets or not selector or selector.get("industry",industry)!=industry:
            continue
        state=source_status(rule,today)
        result["rules_considered"].append({"id":rule["candidate_id"],**state})
        if state["integrity"]!="matched":
            result["warnings"].append(f"{rule['candidate_id']} 来源损坏或缺失，未执行")
            continue
        ids={e for risk in risks if risk.get("pattern_id") in selector.get("patterns",[]) for e in risk["evidence_ids"]}
        ids.update(e.id for e in evidence if any(t in e.text for t in selector.get("terms",[])))
        scenes=[s for s in semantics.get("observations",[]) if s["category"] in selector.get("scene_categories",[])]
        if not ids and not scenes and not selector.get("manual"):
            continue
        result["findings"].append({"rule_id":rule["candidate_id"],"rule_id_type":"internal_candidate_id",
            "platform":rule["platform"],"title":rule["document_title"],"locator":rule["locator"],"rule_summary":rule["rule_summary"],
            "source_url":rule["source_url"],"raw_text_path":rule["raw_text_path"],"source_status":state,
            "evidence_ids":sorted(ids),"scene_ids":[s["observation_id"] for s in scenes],"review_status":"pending_human_review",
            "disposition":"待取得当前有效规则及法务确认","reason":"命中现有候选条款，未证明当前生效；不能按生产规则作通过或拦截结论。"})
    if "小红书" in targets:
        # Preserve the old production gate rather than implicitly enabling pilot rules.
        from src.platform_rules import PlatformRuleRepository
        content="；".join(dict.fromkeys(e.text for e in evidence if e.kind=="text"))[:30000] or "视频未提取到可用文字"
        strict,error=PlatformRuleRepository().precheck({"content":content,"industry":{"化妆品":"美妆","保健食品":"保健食品"}.get(industry,"通用"),
            "platform":["小红书"],"platform_scene":"聚光","material_type":"视频","product_category":product_category,
            "assets":[{"asset_id":"video","type":"video","analysis_status":"not_checked","extracted_text":content}],"landing_page_text":landing_page_text})
        result["production_precheck"]=strict if not error else {"error":error}
    result["warnings"].append("现有条款仍为候选目录；抖音条款来自历史公示，不能视为当前全量规则。投放前需复核官方最新版本。")
    if not landing_page_text:
        result["warnings"].append("未提供落地页文本，广告与落地页一致性未核验")
    return result
