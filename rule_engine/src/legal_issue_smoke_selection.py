# -*- coding: utf-8 -*-
"""Representative three-track rule selection for DeepSeek asset smoke tests."""

import json


SMOKE_TOPICS = {
    "游戏": (
        ("probability", ("概率", "抽卡", "抽取", "掉落", "爆率")),
        ("license", ("版号", "出版", "审批文号")),
        ("minor_payment", ("未成年人", "未成年", "充值", "付费")),
        ("endorsement_experience", ("代言", "体验", "使用过")),
        ("public_morals", ("公序良俗", "低俗", "侮辱", "贬损", "歧视")),
    ),
    "美妆": (
        ("medical_claim", ("医疗", "治疗", "疾病", "药用")),
        ("claim_beyond_filing", ("超备案", "备案", "美白", "祛斑", "防脱")),
        ("special_cosmetics", ("特殊化妆品", "特殊用途", "特妆", "注册证")),
        ("data_experiment", ("数据", "实验", "试验", "检测", "统计")),
        ("endorsement", ("达人", "代言", "推荐", "使用体验")),
    ),
    "保健食品": (
        ("disease_treatment", ("疾病", "治疗", "预防", "降血糖", "降血压")),
        ("drug_substitution", ("替代药物", "替代药品", "无需吃药", "停药")),
        ("efficacy_guarantee", ("功效保证", "保证功效", "有效率", "无效退款")),
        ("ad_preapproval", ("广告审查", "审查批准", "广告批准文号")),
        ("mandatory_warning", ("警示语", "不能代替药物", "本品不能代替药物")),
    ),
}


def _search_text(rule):
    values = {
        "title": rule.get("title"),
        "dimension": rule.get("dimension"),
        "legal_basis": rule.get("legal_basis"),
        "detection": rule.get("detection"),
        "rule_applicability": rule.get("rule_applicability"),
        "fact_check": rule.get("fact_check"),
    }
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def _topic_score(record, keywords):
    text = _search_text(record["rule"])
    title = str(record["rule"].get("title") or "")
    dimension = str(record["rule"].get("dimension") or "")
    return sum(5 for keyword in keywords if keyword in title) + sum(3 for keyword in keywords if keyword in dimension) + sum(1 for keyword in keywords if keyword in text)


def select_representative_smoke_rules(records, per_track=5):
    selected = []
    for track, topics in SMOKE_TOPICS.items():
        pool = [record for record in records if record.get("track") == track]
        used = set()
        for _, keywords in topics:
            ranked = sorted(pool, key=lambda record: (-_topic_score(record, keywords), str(record["rule"].get("rule_uid") or "")))
            winner = next((record for record in ranked if record["rule"].get("rule_uid") not in used and _topic_score(record, keywords) > 0), None)
            if winner:
                selected.append(winner)
                used.add(winner["rule"]["rule_uid"])
            if len(used) >= per_track:
                break
        if len(used) < per_track:
            fallback = sorted(pool, key=lambda record: (str(record["rule"].get("dimension") or ""), str(record["rule"].get("rule_uid") or "")))
            for record in fallback:
                uid = record["rule"].get("rule_uid")
                if uid in used:
                    continue
                selected.append(record)
                used.add(uid)
                if len(used) >= per_track:
                    break
    return selected
