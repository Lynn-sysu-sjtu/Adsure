# -*- coding: utf-8 -*-
"""Review-only v0.2 fingerprint pilot for endorsement-related rules."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

PROMPT_VERSION = "endorsement_fingerprint_v02_20260912"
MODEL = "deepseek-chat"
CONFIDENCE = {"high", "medium", "low"}
LEGAL_EFFECTS = {
    "prohibited", "consent_required", "qualification_check",
    "actual_use_required", "truthfulness_required", "joint_liability",
    "relationship_determination", "disclosure_required", "other",
}
EVIDENCE_REQUIREMENTS = {"content", "fact", "context", "mixed"}

_DIRECT_PATTERN = re.compile(
    r"代言人|广告代言|形象代言|推荐人|证明人|推荐者|证明者|"
    r"(?:专家|机构|科研单位|学术机构|医师|医生|药师).{0,10}(?:推荐|证明)|"
    r"(?:明星|网红|达人|主播|直播人员|直播营销人员).{0,10}(?:代言|推荐|证明)|"
    r"(?:用户|消费者).{0,10}(?:推荐|评价|体验|证明)"
)
_ENDORSEMENT_ACTION_PATTERN = re.compile(r"代言|推荐|作.{0,4}(?:证明|证言)|名义.{0,4}(?:证明|推荐)|形象.{0,4}(?:证明|推荐)")
_CONSENT_TITLE_PATTERN = re.compile(r"广告.{0,20}(?:姓名|名义|名称|形象).{0,20}(?:同意|授权)|未经.{0,10}(?:同意|授权).{0,10}(?:姓名|名义|名称|形象)")
_LIABILITY_TITLE_PATTERN = re.compile(r"连带责任|赔偿责任|损害责任|消费者损害")

_REQUIRED_FIELDS = {
    "rule_uid", "issue_family", "regulated_action", "legal_effect",
    "actor_scope", "object_scope", "channel_scope", "platform_scope",
    "source_type", "legal_level", "legal_basis_key",
    "evidence_requirement", "source_scope_conflict", "recommended_parent",
    "canonical_problem_name", "aliases", "confidence", "reason",
}

PARENT_LABELS = {
    "ENDORSEMENT.RELATION_IDENTIFICATION": "代言关系认定",
    "ENDORSEMENT.PROHIBITED_SUBJECT": "禁止担任代言人的主体",
    "ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY": "特定品类禁止使用推荐人或证明人",
    "ENDORSEMENT.CONSENT_FOR_NAME_IMAGE": "未经同意使用姓名或形象",
    "ENDORSEMENT.ACTUAL_USE_DUTY": "代言人实际使用义务",
    "ENDORSEMENT.TRUTHFULNESS_DUTY": "代言内容真实性义务",
    "ENDORSEMENT.JOINT_LIABILITY": "虚假广告中的连带责任",
    "ENDORSEMENT.OTHER": "其他代言、推荐与证明问题",
}


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _rule_source_text(record):
    rule = record.get("rule") or {}
    parts = [str(rule.get("title") or "")]
    parts.extend(str(item.get("text") or "") for item in rule.get("legal_basis") or [])
    return " ".join(parts)


def select_endorsement_records(records):
    selected = []
    for item in records:
        title = str((item.get("rule") or {}).get("title") or "")
        source_text = _rule_source_text(item)
        direct_title = _DIRECT_PATTERN.search(title) and _ENDORSEMENT_ACTION_PATTERN.search(title)
        consent_title = _CONSENT_TITLE_PATTERN.search(title)
        liability_with_endorser_basis = (
            _LIABILITY_TITLE_PATTERN.search(title)
            and _DIRECT_PATTERN.search(source_text)
            and _ENDORSEMENT_ACTION_PATTERN.search(source_text)
        )
        if direct_title or consent_title or liability_with_endorser_basis:
            selected.append(item)
    return sorted(selected, key=lambda item: (item.get("track") or "", item["rule"]["rule_uid"]))


def validate_fingerprint(item, expected_rule_uid=None):
    missing = _REQUIRED_FIELDS - set(item)
    if missing:
        raise ValueError("missing fingerprint fields: " + ", ".join(sorted(missing)))
    if expected_rule_uid and item.get("rule_uid") != expected_rule_uid:
        raise ValueError("fingerprint rule_uid mismatch")
    if item.get("legal_effect") not in LEGAL_EFFECTS:
        raise ValueError("invalid legal_effect")
    if item.get("evidence_requirement") not in EVIDENCE_REQUIREMENTS:
        raise ValueError("invalid evidence_requirement")
    if item.get("confidence") not in CONFIDENCE:
        raise ValueError("invalid confidence")
    for field in ("actor_scope", "object_scope", "channel_scope", "platform_scope", "legal_basis_key", "aliases"):
        if not isinstance(item.get(field), list):
            raise ValueError(f"{field} must be an array")
    if not isinstance(item.get("legal_level"), int):
        raise ValueError("legal_level must be an integer")
    return item


def parse_fingerprint_batch(payload, expected_rule_uids):
    items = payload.get("fingerprints") or []
    actual = [item.get("rule_uid") for item in items]
    if set(actual) != set(expected_rule_uids) or len(actual) != len(set(actual)):
        raise ValueError("fingerprint batch must contain each expected rule_uid exactly once")
    by_uid = {item["rule_uid"]: validate_fingerprint(item, item["rule_uid"]) for item in items}
    return [by_uid[uid] for uid in expected_rule_uids]


def _group_key(item):
    return str(item.get("legal_effect") or "other")


def build_candidate_groups(fingerprints, max_group_size=50):
    buckets = defaultdict(list)
    for item in fingerprints:
        buckets[_group_key(item)].append(item)
    groups = []
    for key, members in sorted(buckets.items()):
        members = sorted(members, key=lambda item: item["rule_uid"])
        for offset in range(0, len(members), max_group_size):
            chunk = members[offset:offset + max_group_size]
            groups.append({
                "group_id": hashlib.sha256(f"{key}#{offset // max_group_size}".encode()).hexdigest()[:16],
                "group_key": key,
                "rule_uids": [item["rule_uid"] for item in chunk],
                "fingerprints": chunk,
            })
    return groups


def validate_cluster_payload(payload, group):
    clusters = payload.get("clusters") or []
    actual = [uid for item in clusters for uid in item.get("member_rule_uids") or []]
    if set(actual) != set(group["rule_uids"]) or len(actual) != len(set(actual)):
        raise ValueError("cluster coverage mismatch")
    fp_by_uid = {item["rule_uid"]: item for item in group["fingerprints"]}
    for cluster in clusters:
        if cluster.get("confidence") not in CONFIDENCE:
            raise ValueError("invalid cluster confidence")
        if cluster.get("recommended_parent") not in PARENT_LABELS:
            raise ValueError("invalid cluster recommended_parent")
        effects = {fp_by_uid[uid]["legal_effect"] for uid in cluster.get("member_rule_uids") or []}
        if len(effects) > 1:
            raise ValueError("mixed legal_effect cluster is forbidden")
        cluster["legal_effect"] = next(iter(effects)) if effects else "other"
    return clusters


_OBJECT_TRACK = {
    "health_food": "\u4fdd\u5065\u98df\u54c1", "cosmetic": "\u7f8e\u5986", "game": "\u6e38\u620f",
    "pesticide": "\u519c\u836f", "veterinary_drug": "\u517d\u836f", "feed": "\u9972\u6599",
}


def infer_object_scope_from_legal_text(record):
    rule = record.get("rule") or {}
    text = " ".join(str(item.get("text") or "") for item in rule.get("legal_basis") or [])
    scopes = []
    patterns = (
        (r"\u519c\u836f", "pesticide"),
        (r"\u517d\u836f", "veterinary_drug"),
        (r"\u9972\u6599", "feed"),
        (r"\u9972\u6599\u6dfb\u52a0\u5242", "feed_additive"),
        (r"\u4fdd\u5065\u98df\u54c1", "health_food"),
        (r"\u5316\u5986\u54c1", "cosmetic"),
        (r"\u6e38\u620f", "game"),
        (r"\u666e\u901a\u98df\u54c1", "general_food"),
        (r"\u5976\u7c89|\u5a74\u5e7c\u513f\u914d\u65b9|\u7279\u5b9a\u8425\u517b", "milk_powder"),
        (r"\u6559\u80b2|\u57f9\u8bad", "education_training"),
    )
    for pattern, scope in patterns:
        if re.search(pattern, text) and scope not in scopes:
            scopes.append(scope)
    return scopes


_TRACK_COMPATIBLE_SCOPES = {
    "\u4fdd\u5065\u98df\u54c1": {"health_food", "general_food", "milk_powder"},
    "\u7f8e\u5986": {"cosmetic"},
    "\u6e38\u620f": {"game"},
}


def detect_source_scope_conflict(record, object_scope=None):
    legal_scopes = infer_object_scope_from_legal_text(record)
    if not legal_scopes:
        return False
    compatible = _TRACK_COMPATIBLE_SCOPES.get(str(record.get("track") or ""), set())
    regulated = {
        scope for scope in legal_scopes
        if scope in {"health_food", "general_food", "milk_powder", "cosmetic", "game",
                     "pesticide", "veterinary_drug", "feed", "feed_additive",
                     "education_training"}
    }
    return bool(regulated) and regulated.isdisjoint(compatible)


def legal_source_details(record):
    rule = record.get("rule") or {}
    sources = {str(item.get("id")): item for item in record.get("legal_sources") or []}
    details = []
    for basis in rule.get("legal_basis") or []:
        source = sources.get(str(basis.get("source_id"))) or {}
        details.append({
            "source_id": basis.get("source_id"),
            "source_name": source.get("name") or basis.get("source_name") or basis.get("source_id") or "\u672a\u77e5\u6765\u6e90",
            "source_type": source.get("type") or rule.get("source_type") or "",
            "legal_level": int(basis.get("legal_level") or source.get("legal_level") or 99),
            "article": basis.get("article") or "\u672a\u5206\u6761",
            "original_text": basis.get("text") or "",
        })
    return details


def sort_rule_uids_by_legal_hierarchy(rule_uids, records_by_uid, object_scopes=None):
    object_scopes = object_scopes or {}
    def key(uid):
        levels = [item["legal_level"] for item in legal_source_details(records_by_uid[uid])]
        scopes = object_scopes.get(uid) or []
        return min(levels, default=99), 0 if not scopes or "general" in scopes else 1, uid
    return sorted(rule_uids, key=key)



def _normalize_canonical(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


def _record_date(record):
    match = re.search(r"(20\d{6})", str(record.get("source_file") or ""))
    return int(match.group(1)) if match else 0


def _canonical_source_id(record):
    details = legal_source_details(record)
    return str(details[0].get("source_id") or "") if details else ""


def build_canonical_rule_groups(records_by_uid, fingerprints_by_uid):
    buckets = defaultdict(list)
    for uid, record in records_by_uid.items():
        fp = fingerprints_by_uid[uid]
        key_material = "|".join([
            _canonical_source_id(record),
            _normalize_canonical(record["rule"].get("title")),
            str(fp.get("legal_effect") or "other"),
        ])
        key = "CRK-" + hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:16]
        buckets[key].append(uid)
    groups = []
    uid_to_key = {}
    for key, uids in sorted(buckets.items()):
        def score(uid):
            record = records_by_uid[uid]
            fp = fingerprints_by_uid[uid]
            return (
                int(detect_source_scope_conflict(record, fp.get("object_scope") or [])),
                -_record_date(record),
                uid,
            )
        ordered = sorted(uids, key=score)
        canonical_uid = ordered[0]
        group = {
            "canonical_rule_key": key,
            "canonical_rule_uid": canonical_uid,
            "source_occurrence_uids": sorted(uids),
            "duplicate_count": len(uids),
            "source_id": _canonical_source_id(records_by_uid[canonical_uid]),
            "canonical_title": records_by_uid[canonical_uid]["rule"].get("title"),
            "review": {"status": "pending", "notes": None},
        }
        groups.append(group)
        for uid in uids:
            uid_to_key[uid] = key
    return groups, uid_to_key


def should_route_to_proactive(fingerprint, record):
    title = str((record.get("rule") or {}).get("title") or "")
    evidence_action = re.search(r"\u63d0\u4ea4|\u63d0\u4f9b|\u8865\u5145|\u6838\u9a8c", title)
    third_party_proof = re.search(r"\u533b\u751f|\u533b\u5e08|\u4e13\u5bb6|\u673a\u6784", title) and re.search(r"\u8bc1\u660e|\u8d44\u8d28|\u6750\u6599", title)
    return (
        fingerprint.get("legal_effect") == "qualification_check"
        and bool(evidence_action and third_party_proof)
    )

def _compact_rule(record):
    rule = record["rule"]
    return {
        "rule_uid": rule["rule_uid"],
        "track_hint_only": record.get("track"),
        "source_file": record.get("source_file"),
        "source_type": rule.get("source_type"),
        "title": rule.get("title"),
        "dimension": rule.get("dimension"),
        "applies_to": rule.get("applies_to"),
        "preconditions": rule.get("preconditions"),
        "detection": rule.get("detection"),
        "legal_basis": legal_source_details(record),
    }


def fingerprint_messages(records):
    system = (
        "\u4f60\u662f\u5e7f\u544a\u5408\u89c4\u6cd5\u5f8b\u89c4\u5219\u5206\u6790\u5458\u3002\u4ec5\u4f9d\u636e\u89c4\u5219\u6807\u9898\u3001\u9002\u7528\u6761\u4ef6\u3001\u6cd5\u89c4\u6765\u6e90\u548c\u6cd5\u6761\u539f\u6587\u9010\u6761\u751f\u6210\u7ed3\u6784\u5316\u6307\u7eb9\u3002"
        "track_hint_only\u53ea\u662f\u5f31\u63d0\u793a\uff1b\u5982\u679c\u4e0e\u6cd5\u6761\u539f\u6587\u51b2\u7a81\uff0c\u4ee5\u539f\u6587\u4e3a\u51c6\u5e76\u6807\u8bb0source_scope_conflict=true\u3002"
        "\u4e0d\u5f97\u4f9d\u636e\u65e7\u95ee\u9898\u540d\u6216\u65e7\u76ee\u5f55\u3002\u884c\u4e1a\u3001\u54c1\u7c7b\u3001\u5e73\u53f0\u548c\u6e20\u9053\u662f\u9002\u7528\u8303\u56f4\uff0c\u4e0d\u56e0\u8303\u56f4\u4e0d\u540c\u521b\u9020\u4e0d\u540c\u6cd5\u5f8b\u95ee\u9898\u3002"
        "legal_effect\u5fc5\u987b\u4ece\u7ed9\u5b9a\u679a\u4e3e\u9009\u62e9\uff0c\u4e0d\u540clegal_effect\u4e0d\u53ef\u5408\u5e76\u3002\u53ea\u8fd4\u56de\u5408\u6cd5JSON\u3002"
    )
    required = sorted(_REQUIRED_FIELDS)
    user = {
        "task": "\u751f\u6210\u4ee3\u8a00\u3001\u63a8\u8350\u4e0e\u8bc1\u660e\u89c4\u5219\u6307\u7eb9",
        "enums": {
            "legal_effect": sorted(LEGAL_EFFECTS),
            "evidence_requirement": sorted(EVIDENCE_REQUIREMENTS),
            "confidence": sorted(CONFIDENCE),
            "recommended_parent": list(PARENT_LABELS),
        },
        "required_fields": required,
        "rules": [_compact_rule(item) for item in records],
        "output": {"fingerprints": [{
            "rule_uid": "input_rule_uid",
            "issue_family": "stable_ascii_family",
            "regulated_action": "stable_ascii_action",
            "legal_effect": "one_enum_value",
            "actor_scope": ["expert"],
            "object_scope": ["health_food"],
            "channel_scope": [],
            "platform_scope": [],
            "source_type": "law/regulation/platform_rule/other",
            "legal_level": 1,
            "legal_basis_key": ["source_id:article"],
            "evidence_requirement": "content/fact/context/mixed",
            "source_scope_conflict": False,
            "recommended_parent": "one_recommended_parent_enum",
            "canonical_problem_name": "concise_chinese_name",
            "aliases": [],
            "confidence": "high/medium/low",
            "reason": "source_text_support",
        }]},
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def cluster_messages(group):
    system = (
        "\u4f60\u662f\u5e7f\u544a\u5408\u89c4\u6cd5\u5f8b\u95ee\u9898\u5f52\u5e76\u5ba1\u6838\u5458\u3002\u53ea\u6709\u53d7\u89c4\u5236\u884c\u4e3a\u548c\u6cd5\u5f8b\u6548\u679c\u76f8\u540c\u624d\u53efmerge\uff1b"
        "\u884c\u4e1a\u3001\u4ea7\u54c1\u3001\u5e73\u53f0\u3001\u6e20\u9053\u5dee\u5f02\u4f5c\u4e3a\u9002\u7528\u8303\u56f4\u4fdd\u7559\u3002\u4e0d\u540clegal_effect\u7edd\u5bf9\u4e0d\u5f97\u5408\u5e76\u3002"
        "\u6bcf\u4e2arule_uid\u5fc5\u987b\u4e14\u53ea\u80fd\u51fa\u73b0\u4e00\u6b21\uff0c\u4e0d\u5f97\u65b0\u589e\u89c4\u5219\u3002\u53ea\u8fd4\u56de\u5408\u6cd5JSON\u3002"
    )
    user = {
        "task": "\u5f52\u5e76\u5019\u9009\u89c4\u5219\u6307\u7eb9",
        "group_id": group["group_id"],
        "fingerprints": group["fingerprints"],
        "recommended_parent_options": PARENT_LABELS,
        "instruction": "聚类阶段必须重新选择recommended_parent，可以纠正单条指纹的初始父节点。",
        "output": {"clusters": [{
            "cluster_key": "ASCII_KEY", "canonical_name": "\u4e2d\u6587\u6807\u51c6\u95ee\u9898\u540d",
            "member_rule_uids": ["input_rule_uid"], "relation": "merge/separate",
            "recommended_parent": "one_recommended_parent_enum",
            "confidence": "high/medium/low", "reason": "\u57fa\u4e8e\u6cd5\u5f8b\u8981\u4ef6\u7684\u7406\u7531",
        }]},
    }
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def _response_payload(response):
    content = response["choices"][0]["message"]["content"]
    return json.loads(content)


def call_with_checkpoint(client, messages, checkpoint, validator=None):
    checkpoint = Path(checkpoint)
    digest = hashlib.sha256(
        json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8-sig"))
        if saved.get("digest") == digest and saved.get("model") == MODEL:
            payload = saved["payload"]
            return validator(payload) if validator else payload
    response = client.create_chat_completion(
        messages=messages, model=MODEL, temperature=0.0,
        response_format={"type": "json_object"},
    )
    payload = _response_payload(response)
    result = validator(payload) if validator else payload
    _atomic_json(checkpoint, {
        "digest": digest, "model": MODEL, "prompt_version": PROMPT_VERSION,
        "payload": payload,
    })
    return result


def build_proactive_check(fingerprint, record):
    uid = fingerprint["rule_uid"]
    return {
        "check_id": "PC-ENDORSEMENT-" + hashlib.sha256(uid.encode("utf-8")).hexdigest()[:12],
        "name": "\u666e\u901a\u98df\u54c1\u533b\u751f\u63a8\u8350\u8bc1\u660e\u6838\u9a8c",
        "opinion_type": "\u9700\u8865\u8d44\u6599",
        "trigger_conditions": {
            "industry_or_product_scope": ["general_food"],
            "content_signals": ["doctor_recommendation"],
            "context_requirement": "\u5f85\u5ba1\u6838\u6587\u6848\u6216\u6295\u653e\u80cc\u666f\u51fa\u73b0\u533b\u751f\u63a8\u8350",
            "missing_materials_required": True,
        },
        "required_materials": [
            "\u533b\u751f\u8eab\u4efd\u8bc1\u660e\u6216\u6267\u4e1a\u8d44\u8d28",
            "\u533b\u751f\u63a8\u8350\u3001\u6388\u6743\u6216\u5408\u4f5c\u5173\u7cfb\u6750\u6599",
        ],
        "source_rule_uids": [uid],
        "source_details": legal_source_details(record),
        "review": {"status": "pending", "notes": None},
    }


def assemble_draft_assets(fingerprints, clusters, records_by_uid):
    fingerprint_by_uid = {item["rule_uid"]: item for item in fingerprints}
    proactive_uids = {
        uid for uid, fp in fingerprint_by_uid.items()
        if should_route_to_proactive(fp, records_by_uid[uid])
    }
    legal_clusters = []
    for cluster in clusters:
        legal_members = [
            uid for uid in cluster.get("member_rule_uids") or []
            if uid not in proactive_uids
        ]
        if legal_members:
            legal_cluster = dict(cluster)
            legal_cluster["member_rule_uids"] = legal_members
            legal_clusters.append(legal_cluster)

    canonical_groups, uid_to_key = build_canonical_rule_groups(
        records_by_uid, fingerprint_by_uid
    )
    canonical_by_key = {
        item["canonical_rule_key"]: item for item in canonical_groups
    }
    used_parents = []
    rules_by_parent = defaultdict(list)
    cluster_rows_by_parent = defaultdict(list)
    uid_to_parent = {}
    for cluster in legal_clusters:
        parent = cluster.get("recommended_parent") or "ENDORSEMENT.OTHER"
        if parent not in PARENT_LABELS:
            parent = "ENDORSEMENT.OTHER"
        if parent not in used_parents:
            used_parents.append(parent)
        members = cluster.get("member_rule_uids") or []
        rules_by_parent[parent].extend(members)
        cluster_rows_by_parent[parent].append(cluster)
        for uid in members:
            uid_to_parent[uid] = parent

    nodes = [{
        "issue_id": "ENDORSEMENT",
        "parent_issue_id": None,
        "level": 1,
        "node_type": "directory",
        "name": "\u4ee3\u8a00\u3001\u63a8\u8350\u4e0e\u8bc1\u660e",
        "rule_uids": [],
    }]
    subject_children = {
        "ENDORSEMENT.PROHIBITED_SUBJECT",
        "ENDORSEMENT.PROHIBITED_RECOMMENDER_BY_CATEGORY",
    }
    if subject_children.intersection(used_parents):
        nodes.append({
            "issue_id": "ENDORSEMENT.SUBJECT_ELIGIBILITY",
            "parent_issue_id": "ENDORSEMENT",
            "level": 2,
            "node_type": "directory",
            "name": "\u4ee3\u8a00\u4e3b\u4f53\u8d44\u683c\u4e0e\u9650\u5236",
            "rule_uids": [],
        })

    object_scopes = {
        uid: item.get("object_scope") or []
        for uid, item in fingerprint_by_uid.items()
    }
    for parent in PARENT_LABELS:
        if parent not in used_parents:
            continue
        occurrence_uids = sort_rule_uids_by_legal_hierarchy(
            list(dict.fromkeys(rules_by_parent[parent])),
            records_by_uid, object_scopes,
        )
        canonical_uids = []
        seen_keys = set()
        for uid in occurrence_uids:
            key = uid_to_key[uid]
            if key not in seen_keys:
                canonical_uids.append(canonical_by_key[key]["canonical_rule_uid"])
                seen_keys.add(key)
        nested = parent in subject_children
        nodes.append({
            "issue_id": parent,
            "parent_issue_id": "ENDORSEMENT.SUBJECT_ELIGIBILITY" if nested else "ENDORSEMENT",
            "level": 3 if nested else 2,
            "node_type": "legal_issue",
            "name": PARENT_LABELS[parent],
            "rule_uids": canonical_uids,
            "source_occurrence_uids": occurrence_uids,
            "candidate_clusters": cluster_rows_by_parent[parent],
        })

    mappings = []
    for uid, record in sorted(records_by_uid.items()):
        fp = fingerprint_by_uid[uid]
        canonical_key = uid_to_key[uid]
        canonical_group = canonical_by_key[canonical_key]
        if uid in proactive_uids:
            issue_id = None
            mapping_type = "proactive_check"
        else:
            issue_id = uid_to_parent[uid]
            mapping_type = "legal_issue"
        mappings.append({
            "rule_uid": uid,
            "rule_id": record["rule"].get("rule_id"),
            "rule_title": record["rule"].get("title"),
            "issue_id": issue_id,
            "mapping_type": mapping_type,
            "canonical_rule_key": canonical_key,
            "canonical_rule_uid": canonical_group["canonical_rule_uid"],
            "is_canonical_occurrence": uid == canonical_group["canonical_rule_uid"],
            "track": record.get("track"),
            "source_file": record.get("source_file"),
            "source_details": legal_source_details(record),
            "fingerprint": fp,
            "review": {"status": "pending", "notes": None},
        })

    proactive_checks = [
        build_proactive_check(fingerprint_by_uid[uid], records_by_uid[uid])
        for uid in sorted(proactive_uids)
    ]
    expected = set(fingerprint_by_uid)
    actual = [item["rule_uid"] for item in mappings]
    if set(actual) != expected or len(actual) != len(set(actual)):
        raise ValueError("assembled mapping does not preserve rule_uid coverage")
    issue_nodes = [item for item in nodes if item["node_type"] == "legal_issue"]
    if any(not item["rule_uids"] for item in issue_nodes):
        raise ValueError("source-less legal issue node")
    stamp = {
        "schema_version": "0.2",
        "asset_status": "draft",
        "prompt_version": PROMPT_VERSION,
        "model": MODEL,
    }
    return {
        "taxonomy": {**stamp, "nodes": nodes},
        "mapping": {**stamp, "mappings": mappings},
        "fingerprints": {**stamp, "fingerprints": fingerprints},
        "clusters": {**stamp, "clusters": legal_clusters},
        "canonical_rules": {**stamp, "groups": canonical_groups},
        "proactive_checks": {**stamp, "checks": proactive_checks},
    }

def export_review_workbook(path, assets):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    workbook = Workbook()
    tree = workbook.active
    tree.title = "\u95ee\u9898\u6811"
    tree.append(["\u5c42\u7ea7", "\u8282\u70b9\u7c7b\u578b", "\u95ee\u9898ID", "\u7236\u8282\u70b9ID", "\u95ee\u9898\u540d\u79f0", "\u6807\u51c6\u89c4\u8303\u6570", "\u6765\u6e90\u8bb0\u5f55\u6570", "\u4eba\u5de5\u7ed3\u8bba", "\u5907\u6ce8"])
    for node in assets["taxonomy"]["nodes"]:
        tree.append([node.get("level"), node.get("node_type"), node.get("issue_id"), node.get("parent_issue_id"), node.get("name"), len(node.get("rule_uids") or []), len(node.get("source_occurrence_uids") or []), "", ""])

    clusters = workbook.create_sheet("\u805a\u7c7b\u7ed3\u679c\u5ba1\u6838")
    clusters.append(["\u6700\u7ec8\u95ee\u9898", "\u6807\u51c6\u95ee\u9898\u540d", "\u6cd5\u5f8b\u6548\u679c", "\u6765\u6e90\u6570", "rule_uid", "\u7f6e\u4fe1\u5ea6", "\u6a21\u578b\u7406\u7531", "\u4eba\u5de5\u7ed3\u8bba", "\u5907\u6ce8"])
    for item in assets["clusters"]["clusters"]:
        clusters.append([PARENT_LABELS.get(item.get("recommended_parent"), item.get("recommended_parent")), item.get("canonical_name"), item.get("legal_effect"), len(item.get("member_rule_uids") or []), "\n".join(item.get("member_rule_uids") or []), item.get("confidence"), item.get("reason"), "", ""])

    mappings = assets["mapping"]["mappings"]
    by_uid = {item["rule_uid"]: item for item in mappings}
    canonical = workbook.create_sheet("\u6807\u51c6\u89c4\u8303\u53bb\u91cd")
    canonical.append(["canonical_rule_key", "\u6807\u51c6rule_uid", "\u6807\u51c6\u89c4\u5219\u6807\u9898", "\u6765\u6e90\u6570", "\u6765\u6e90rule_uid", "\u6765\u6e90\u8d5b\u9053", "\u6765\u6e90\u6587\u4ef6", "\u4eba\u5de5\u7ed3\u8bba", "\u5907\u6ce8"])
    for group in assets["canonical_rules"]["groups"]:
        uids = group["source_occurrence_uids"]
        canonical.append([group["canonical_rule_key"], group["canonical_rule_uid"], group.get("canonical_title"), len(uids), "\n".join(uids), "\n".join(str(by_uid[uid].get("track") or "") for uid in uids), "\n".join(str(by_uid[uid].get("source_file") or "") for uid in uids), "", ""])

    names = {node["issue_id"]: node["name"] for node in assets["taxonomy"]["nodes"]}
    check_names = {uid: check["name"] for check in assets["proactive_checks"]["checks"] for uid in check["source_rule_uids"]}
    detail = workbook.create_sheet("\u95ee\u9898-\u89c4\u5219\u539f\u6587")
    detail.append(["\u6620\u5c04\u7c7b\u578b", "\u5f52\u5c5e", "canonical_rule_key", "\u6807\u51c6rule_uid", "rule_uid", "\u662f\u5426\u6807\u51c6\u6765\u6e90", "\u8d5b\u9053", "\u89c4\u5219\u6807\u9898", "\u5bf9\u8c61\u8303\u56f4", "\u6cd5\u5f8b\u6548\u679c", "\u6cd5\u89c4\u540d\u79f0", "\u6761\u6b3e", "\u89c4\u5219\u539f\u6587", "\u6765\u6e90\u8303\u56f4\u51b2\u7a81", "\u7f6e\u4fe1\u5ea6", "\u4eba\u5de5\u7ed3\u8bba", "\u5907\u6ce8"])
    for item in mappings:
        fp = item["fingerprint"]
        label = names.get(item.get("issue_id")) or check_names.get(item["rule_uid"])
        for source in item["source_details"] or [{}]:
            detail.append([item["mapping_type"], label, item["canonical_rule_key"], item["canonical_rule_uid"], item["rule_uid"], item["is_canonical_occurrence"], item.get("track"), item.get("rule_title"), ", ".join(fp.get("object_scope") or []), fp.get("legal_effect"), source.get("source_name"), source.get("article"), source.get("original_text"), fp.get("source_scope_conflict"), fp.get("confidence"), "", ""])

    proactive = workbook.create_sheet("\u4e3b\u52a8\u8865\u8d44\u6599\u6838\u67e5")
    proactive.append(["check_id", "\u6838\u67e5\u9879", "\u610f\u89c1\u7c7b\u578b", "\u89e6\u53d1\u6761\u4ef6", "\u9700\u8865\u6750\u6599", "\u6765\u6e90rule_uid", "\u6cd5\u6761\u539f\u6587", "\u4eba\u5de5\u7ed3\u8bba", "\u5907\u6ce8"])
    for check in assets["proactive_checks"]["checks"]:
        proactive.append([check["check_id"], check["name"], check["opinion_type"], json.dumps(check["trigger_conditions"], ensure_ascii=False), "\n".join(check["required_materials"]), "\n".join(check["source_rule_uids"]), "\n".join(x.get("original_text") or "" for x in check["source_details"]), "", ""])

    fingerprints = workbook.create_sheet("\u7ed3\u6784\u5316\u6307\u7eb9")
    fields = sorted(_REQUIRED_FIELDS)
    fingerprints.append(fields)
    for fp in assets["fingerprints"]["fingerprints"]:
        fingerprints.append([json.dumps(fp.get(field), ensure_ascii=False) if isinstance(fp.get(field), (list, dict)) else fp.get(field) for field in fields])

    focus = workbook.create_sheet("\u5f85\u4eba\u5de5\u91cd\u70b9\u5ba1\u6838")
    focus.append([
        "rule_uid", "\u5f52\u5c5e", "\u5ba1\u6838\u539f\u56e0", "\u89c4\u5219\u6807\u9898", "\u539f\u59cb\u8d5b\u9053", "\u6765\u6e90\u6587\u4ef6",
        "\u6765\u6e90\u7c7b\u578b", "\u6cd5\u89c4/\u5e73\u53f0\u89c4\u5219\u540d\u79f0", "\u6761\u6b3e", "\u89c4\u5219\u539f\u6587", "\u6a21\u578b\u8bc6\u522b\u9002\u7528\u5bf9\u8c61",
        "\u6cd5\u5f8b\u6548\u679c", "canonical_rule_key", "\u6807\u51c6rule_uid", "\u5176\u4ed6\u91cd\u590d\u6765\u6e90rule_uid",
        "\u5efa\u8bae\u5224\u65ad", "\u7f6e\u4fe1\u5ea6", "\u4eba\u5de5\u7ed3\u8bba", "\u8c03\u6574\u540e\u7684\u5f52\u5c5e", "\u5907\u6ce8",
    ])
    group_by_key = {x["canonical_rule_key"]: x for x in assets["canonical_rules"]["groups"]}
    for item in mappings:
        fp = item["fingerprint"]
        reasons = []
        if fp.get("source_scope_conflict"):
            reasons.append("\u8d5b\u9053\u6216\u6807\u9898\u4e0e\u6cd5\u6761\u539f\u6587\u51b2\u7a81")
        if item["mapping_type"] == "proactive_check":
            reasons.append("\u5df2\u8fc1\u5165\u4e3b\u52a8\u8865\u8d44\u6599\u94fe\u8def")
        group = group_by_key[item["canonical_rule_key"]]
        if group["duplicate_count"] > 1:
            reasons.append("\u91cd\u590d\u6765\u6e90\u8bb0\u5f55")
        if fp.get("confidence") != "high":
            reasons.append("\u4e2d\u4f4e\u6307\u7eb9\u7f6e\u4fe1\u5ea6")
        if reasons:
            duplicate_uids = [uid for uid in group["source_occurrence_uids"] if uid != item["rule_uid"]]
            sources = item.get("source_details") or [{}]
            suggestions = []
            if fp.get("source_scope_conflict"):
                suggestions.append("\u6838\u5bf9\u539f\u6587\u9002\u7528\u8303\u56f4\uff1b\u786e\u8ba4\u76ee\u5f55\u6c61\u67d3\u6216\u4fdd\u7559\u5f53\u524d\u5f52\u5c5e")
            if group["duplicate_count"] > 1:
                suggestions.append("\u6838\u5bf9\u6765\u6e90\u3001\u6761\u6b3e\u3001\u6838\u5fc3\u539f\u6587\u548c\u6cd5\u5f8b\u6548\u679c\uff1b\u5408\u5e76\u6216\u72ec\u7acb\u4fdd\u7559")
            if item["mapping_type"] == "proactive_check":
                suggestions.append("\u6838\u5bf9\u662f\u5426\u4ec5\u8981\u6c42\u8bc1\u660e\u6750\u6599\uff1b\u4fdd\u7559\u8865\u8d44\u6599\u6216\u8fd4\u56de\u6cd5\u5f8b\u95ee\u9898\u6811")
            if fp.get("confidence") != "high":
                suggestions.append("\u6838\u5bf9\u6307\u7eb9\u662f\u5426\u5fe0\u4e8e\u539f\u6587")
            focus.append([
                item["rule_uid"], names.get(item.get("issue_id")) or check_names.get(item["rule_uid"]),
                "\uff1b".join(reasons), item.get("rule_title"), item.get("track"), item.get("source_file"),
                "\n".join(str(source.get("source_type") or "") for source in sources),
                "\n".join(str(source.get("source_name") or "") for source in sources),
                "\n".join(str(source.get("article") or "") for source in sources),
                "\n\n".join(str(source.get("original_text") or "") for source in sources),
                ", ".join(fp.get("object_scope") or []), fp.get("legal_effect"), item["canonical_rule_key"],
                item["canonical_rule_uid"], "\n".join(duplicate_uids), "\n".join(suggestions),
                fp.get("confidence"), "", "", "",
            ])

    decisions = [
        "\u786e\u8ba4\u76ee\u524d\u5f52\u5c5e", "\u786e\u8ba4\u76ee\u5f55\u6c61\u67d3", "\u5408\u5e76\u4e3a\u540c\u4e00\u6807\u51c6\u89c4\u8303", "\u72ec\u7acb\u4fdd\u7559",
        "\u4fdd\u7559\u5728\u4e3b\u52a8\u8865\u8d44\u6599", "\u8fd4\u56de\u6cd5\u5f8b\u95ee\u9898\u6811", "\u65e0\u6cd5\u786e\u5b9a",
    ]
    decision_validation = DataValidation(type="list", formula1='"' + ",".join(decisions) + '"', allow_blank=True)
    focus.add_data_validation(decision_validation)
    if focus.max_row >= 2:
        decision_validation.add(f"R2:R{focus.max_row}")
        for row in focus.iter_rows(min_row=2, min_col=18, max_col=20):
            for cell in row:
                cell.fill = PatternFill("solid", fgColor="FFF2CC")

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="294C60")
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for column in sheet.columns:
            letter = column[0].column_letter
            sheet.column_dimensions[letter].width = min(55, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def export_review_html(path, assets):
    from html import escape
    nodes = assets["taxonomy"]["nodes"]
    mappings = assets["mapping"]["mappings"]
    children = defaultdict(list)
    for node in nodes:
        children[node.get("parent_issue_id")].append(node)
    canonical = {x["canonical_rule_key"]: x for x in assets["canonical_rules"]["groups"]}
    by_issue = defaultdict(list)
    for item in mappings:
        if item["mapping_type"] == "legal_issue":
            by_issue[item["issue_id"]].append(item)

    def source_card(item):
        sources = "".join(f'<div class="source"><b>{escape(str(x.get("source_name") or ""))} {escape(str(x.get("article") or ""))}</b><p>{escape(str(x.get("original_text") or ""))}</p></div>' for x in item["source_details"])
        warning = '<strong class="warn">\u8d5b\u9053\u6216\u6807\u9898\u4e0e\u6cd5\u6761\u539f\u6587\u51b2\u7a81\uff0c\u4ee5\u539f\u6587\u4e3a\u51c6</strong>' if item["fingerprint"].get("source_scope_conflict") else ""
        return f'<details class="occurrence"><summary>{escape(item["rule_uid"])} | {escape(str(item.get("track") or ""))} | {escape(str(item.get("source_file") or ""))}</summary>{warning}{sources}</details>'

    def issue_card(node):
        grouped = defaultdict(list)
        for item in by_issue[node["issue_id"]]:
            grouped[item["canonical_rule_key"]].append(item)
        rules = []
        for key, occurrences in sorted(grouped.items()):
            group = canonical[key]
            rules.append(f'<details class="rule"><summary>{escape(group["canonical_rule_uid"])} | {escape(str(group.get("canonical_title") or ""))}<small>{len(occurrences)} \u4e2a\u6765\u6e90\u8bb0\u5f55</small></summary><div class="key">{escape(key)}</div>{"".join(source_card(x) for x in occurrences)}</details>')
        cluster_items = "".join(f'<li><b>{escape(str(x.get("canonical_name") or ""))}</b><small>{len(x.get("member_rule_uids") or [])} \u4e2a\u6765\u6e90\u8bb0\u5f55 | {escape(str(x.get("confidence") or ""))}</small></li>' for x in node.get("candidate_clusters") or [])
        return f'<details class="issue" open><summary>{escape(node["name"])}<small>{len(node.get("rule_uids") or [])} \u6761\u6807\u51c6\u89c4\u8303</small></summary><div class="clusters"><h3>\u5f52\u5e76\u95ee\u9898\u7c07</h3><ul>{cluster_items}</ul></div>{"".join(rules)}</details>'

    def render(node):
        if node["node_type"] == "legal_issue":
            return issue_card(node)
        return f'<details class="directory" open><summary>{escape(node["name"])}</summary>{"".join(render(x) for x in children[node["issue_id"]])}</details>'

    tree = "".join(render(x) for x in children["ENDORSEMENT"])
    checks = []
    for check in assets["proactive_checks"]["checks"]:
        sources = "".join(f'<div class="source"><b>{escape(str(x.get("source_name") or ""))} {escape(str(x.get("article") or ""))}</b><p>{escape(str(x.get("original_text") or ""))}</p></div>' for x in check["source_details"])
        source_uids = "\u3001".join(str(uid) for uid in check.get("source_rule_uids") or [])
        checks.append(f'<details class="proactive" open><summary>{escape(check["name"])}<small>{escape(check["opinion_type"])}</small></summary><div class="key">\u6765\u6e90\u89c4\u5219\uff1a{escape(source_uids)}</div><p><b>\u9700\u8865\u6750\u6599\uff1a</b>{escape("\uff1b".join(check["required_materials"]))}</p>{sources}</details>')
    proactive = '<section><h2>\u4e3b\u52a8\u8865\u8d44\u6599\u6838\u67e5</h2>' + "".join(checks) + "</section>" if checks else ""
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>\u4ee3\u8a00\u63a8\u8350\u8bc1\u660e\u95ee\u9898\u6811 v0.3</title>
<style>body{{font-family:"Microsoft YaHei",sans-serif;margin:0;background:#f5f7f8;color:#17252a}}header{{background:#173f4f;color:#fff;padding:24px 5vw}}main{{max-width:1120px;margin:24px auto;padding:0 20px}}.directory,.issue,.rule,.proactive,.occurrence{{background:#fff;border:1px solid #d9e1e4;border-radius:6px;margin:10px 0;padding:12px}}.directory>summary{{font-size:20px;font-weight:700}}.issue>summary{{font-size:17px;font-weight:700}}summary{{cursor:pointer}}small{{color:#567;margin-left:10px}}.source{{border-left:3px solid #3b7c8d;padding:8px 12px;margin:10px 0;background:#f8fbfc}}.source p{{white-space:pre-wrap;line-height:1.65}}.warn{{display:block;color:#b42318;margin:8px 0}}.clusters{{background:#eef5f6;padding:10px 16px;margin:12px 0}}.key{{font:12px Consolas;color:#567;margin:8px 0}}section{{margin-top:28px}}</style></head>
<body><header><h1>\u4ee3\u8a00\u3001\u63a8\u8350\u4e0e\u8bc1\u660e\u95ee\u9898\u6811</h1><p>\u6807\u51c6\u89c4\u8303\u53bb\u91cd + \u6765\u6e90\u8bb0\u5f55\u8ffd\u6eaf | \u4ec5\u4f9b\u5ba1\u6838</p></header><main>{tree}{proactive}</main></body></html>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


def build_singleton_cluster(fp):
    return {
        "cluster_key": fp["regulated_action"].upper(),
        "canonical_name": fp["canonical_problem_name"],
        "member_rule_uids": [fp["rule_uid"]],
        "relation": "separate",
        "confidence": fp["confidence"],
        "reason": "\u5019\u9009\u7ec4\u4ec5\u542b\u4e00\u6761\u89c4\u5219\uff0c\u4fdd\u7559\u4e3a\u72ec\u7acb\u5019\u9009\u3002",
        "recommended_parent": fp["recommended_parent"],
        "legal_effect": fp["legal_effect"],
    }

def _validated_call_with_repair(client, messages, checkpoint, validator):
    try:
        return call_with_checkpoint(client, messages, checkpoint, validator)
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        repair_messages = list(messages) + [{
            "role": "user",
            "content": (
                "\u4e0a\u4e00\u6b21\u8f93\u51fa\u672a\u901a\u8fc7Python\u786e\u5b9a\u6027\u6821\u9a8c\u3002"
                "\u8bf7\u4e25\u683c\u4fee\u590dJSON\u7ed3\u6784\u3001\u679a\u4e3e\u503c\u548crule_uid\u5b8c\u6574\u8986\u76d6\uff0c"
                "\u4e0d\u5f97\u6539\u53d8\u89c4\u5219\u4e8b\u5b9e\u3002\u6821\u9a8c\u9519\u8bef\uff1a" + str(exc)
            ),
        }]
        repair_path = Path(checkpoint).with_name(Path(checkpoint).stem + "_repair.json")
        return call_with_checkpoint(client, repair_messages, repair_path, validator)


def _chunks(items, size):
    for offset in range(0, len(items), size):
        yield offset // size, items[offset:offset + size]


def run_pilot(records, client, assets_dir, report_dir, batch_size=4, smoke_limit=None):
    assets_dir = Path(assets_dir)
    report_dir = Path(report_dir)
    checkpoints = report_dir / "checkpoints"
    selected = select_endorsement_records(records)
    if smoke_limit:
        selected = selected[:smoke_limit]
    records_by_uid = {item["rule"]["rule_uid"]: item for item in selected}
    fingerprints = []
    for index, batch in _chunks(selected, batch_size):
        expected = [item["rule"]["rule_uid"] for item in batch]
        validator = lambda payload, expected=expected: parse_fingerprint_batch(payload, expected)
        generated = _validated_call_with_repair(
            client, fingerprint_messages(batch),
            checkpoints / "fingerprints" / f"{index:03d}.json", validator,
        )
        for item in generated:
            record = records_by_uid[item["rule_uid"]]
            inferred_scopes = infer_object_scope_from_legal_text(record)
            if inferred_scopes:
                item["object_scope"] = inferred_scopes
            item["source_scope_conflict"] = detect_source_scope_conflict(
                record, item.get("object_scope") or []
            )
        fingerprints.extend(generated)

    groups = build_candidate_groups(fingerprints)
    clusters = []
    for group in groups:
        if len(group["rule_uids"]) == 1:
            fp = group["fingerprints"][0]
            clusters.append(build_singleton_cluster(fp))
            continue
        validator = lambda payload, group=group: validate_cluster_payload(payload, group)
        generated = _validated_call_with_repair(
            client, cluster_messages(group),
            checkpoints / "clusters" / f"{group['group_id']}.json", validator,
        )
        clusters.extend(generated)

    assets = assemble_draft_assets(fingerprints, clusters, records_by_uid)
    output_map = {
        "endorsement_issue_fingerprints_draft_v0.3.json": assets["fingerprints"],
        "endorsement_candidate_clusters_draft_v0.3.json": assets["clusters"],
        "endorsement_issue_taxonomy_draft_v0.3.json": assets["taxonomy"],
        "endorsement_rule_mapping_draft_v0.3.json": assets["mapping"],
        "endorsement_canonical_rule_groups_draft_v0.3.json": assets["canonical_rules"],
        "endorsement_proactive_checklist_draft_v0.3.json": assets["proactive_checks"],
    }
    for name, payload in output_map.items():
        _atomic_json(assets_dir / name, payload)
    workbook = export_review_workbook(
        report_dir / "\u4ee3\u8a00\u63a8\u8350\u8bc1\u660e\u95ee\u9898\u6811\u4eba\u5de5\u5ba1\u6838\u8868.xlsx", assets
    )
    html_path = export_review_html(
        report_dir / "\u4ee3\u8a00\u63a8\u8350\u8bc1\u660e\u95ee\u9898\u6811.html", assets
    )
    fingerprint_uids = [item["rule_uid"] for item in fingerprints]
    mapping_uids = [item["rule_uid"] for item in assets["mapping"]["mappings"]]
    low_medium = sum(item["confidence"] != "high" for item in fingerprints)
    conflicts = sum(bool(item["source_scope_conflict"]) for item in fingerprints)
    used_parents = [
        node["issue_id"] for node in assets["taxonomy"]["nodes"]
        if node["node_type"] == "legal_issue"
    ]
    summary = {
        "asset_status": "draft",
        "model": MODEL,
        "prompt_version": PROMPT_VERSION,
        "selected_rule_count": len(selected),
        "fingerprint_count": len(fingerprints),
        "candidate_group_count": len(groups),
        "cluster_count": len(assets["clusters"]["clusters"]),
        "canonical_rule_count": len(assets["canonical_rules"]["groups"]),
        "duplicate_canonical_group_count": sum(
            item.get("duplicate_count", 1) > 1
            for item in assets["canonical_rules"]["groups"]
        ),
        "proactive_check_count": len(assets["proactive_checks"]["checks"]),
        "source_scope_conflict_count": conflicts,
        "low_or_medium_fingerprint_count": low_medium,
        "low_or_medium_cluster_count": sum(
            c.get("confidence") != "high"
            for c in assets["clusters"]["clusters"]
        ),
        "rule_uid_preserved": (
            set(records_by_uid) == set(fingerprint_uids) == set(mapping_uids)
            and len(mapping_uids) == len(set(mapping_uids))
        ),
        "source_less_issue_count": sum(
            not node.get("rule_uids") for node in assets["taxonomy"]["nodes"]
            if node["node_type"] == "legal_issue"
        ),
        "formed_target_branches": {
            key: key in used_parents for key in PARENT_LABELS if key != "ENDORSEMENT.OTHER"
        },
        "output_files": {
            "workbook": str(workbook),
            "html": str(html_path),
            "assets": [str(assets_dir / name) for name in output_map],
        },
    }
    _atomic_json(report_dir / "pilot_summary.json", summary)
    return summary
