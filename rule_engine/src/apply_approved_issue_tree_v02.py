# -*- coding: utf-8 -*-
"""Build approved v0.2 review assets without changing v0.1 or jsonbase."""

from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from jsonbase_correction_issue_tree import correct_issue_assets

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from export_all_primary_issue_tree_html import ROOT_ORDER, flatten_tree, load_combined_tree
from export_issue_rule_grouped_workbook import load_mapping_rows


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "reports" / "approved_issue_tree_v02"

NEW_NODES = [
    ("EFFICACY_PERFORMANCE.DISEASE_MEDICAL.SPECIAL_MEDICAL_FOOD_AD_OVER_REGISTERED_SCOPE", "EFFICACY_PERFORMANCE.DISEASE_MEDICAL", 3, "特殊医学用途配方食品广告内容超出注册证书或标签说明书范围"),
    ("EFFICACY_PERFORMANCE.DISEASE_MEDICAL.DRUG_AD_OVER_INSTRUCTION_SCOPE", "EFFICACY_PERFORMANCE.DISEASE_MEDICAL", 3, "药品广告内容超出核准说明书范围"),
    ("EFFICACY_PERFORMANCE.DISEASE_MEDICAL.MEDICAL_DEVICE_AD_OVER_REGISTERED_SCOPE", "EFFICACY_PERFORMANCE.DISEASE_MEDICAL", 3, "医疗器械广告内容超出注册、备案或说明书范围"),
    ("CLAIM_EXPRESSION.ABSOLUTE.RANKING_UNIQUENESS_TERMS", "CLAIM_EXPRESSION.ABSOLUTE", 3, "比较、排名与唯一性宣称"),
    ("MINORS_PUBLIC_ORDER.AD_TARGETING_MEDIA", "MINORS_PUBLIC_ORDER", 2, "广告定向、发布场所与媒介限制"),
    ("MINORS_PUBLIC_ORDER.PROHIBITED_SALES", "MINORS_PUBLIC_ORDER", 2, "禁止向未成年人销售或宣传特定商品"),
    ("MINORS_PUBLIC_ORDER.PERSONAL_INFORMATION", "MINORS_PUBLIC_ORDER", 2, "未成年人个人信息保护"),
    ("MINORS_PUBLIC_ORDER.PUBLIC_MORALITY.DEFAMATION_INSULT", "MINORS_PUBLIC_ORDER.PUBLIC_MORALITY", 3, "侮辱诽谤"),
    ("MINORS_PUBLIC_ORDER.DISCRIMINATION_INSULT.MINOR_ACCESS_RESTRICTION_VIOLATION", "MINORS_PUBLIC_ORDER.DISCRIMINATION_INSULT", 3, "违反未成年人禁入限入规定或未核验年龄"),
    ("MATERIAL_PLATFORM.LANDING_PAGE_JUMP", "MATERIAL_PLATFORM", 2, "落地页与跳转规范"),
    ("MATERIAL_PLATFORM.DISPLAY_CLOSE", "MATERIAL_PLATFORM", 2, "广告展示行为与关闭规范"),
    ("MATERIAL_PLATFORM.PLACEMENT_SPEC_FREQUENCY", "MATERIAL_PLATFORM", 2, "广告位、投放规格与频次"),
]

REMOVE_NODES = {
    "SCOPE_ACCESS.PRODUCT_REGISTRATION",
    "SCOPE_ACCESS.SCOPE_CLASSIFICATION.CROSS_CATEGORY_EFFICACY_CLAIM",
    "SCOPE_ACCESS.SUBJECT_QUALIFICATION.BRAND_NAME_NON_DISTINCTIVE_OR_NON_EXCLUSIVE",
    "SCOPE_ACCESS.SUBJECT_QUALIFICATION.HEALTH_FOOD_LICENSE_COMPLIANCE",
    "SCOPE_ACCESS.SUBJECT_QUALIFICATION.GAME_REAL_NAME_REGISTRATION_REQUIREMENT",
    "PROHIBITED_CONTENT.PROHIBITED_PRODUCTS.DISGUISED_ADVERTISING_HEALTH_WELLNESS",
    "CLAIM_EXPRESSION.AMBIGUOUS_EXAGGERATED.INSTANT_EFFECT_EXAGGERATION",
    "CLAIM_EXPRESSION.COMPARATIVE_RANKING",
    "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.HEALTH_FOOD_DISEASE_WORD_OR_EXAGGERATED_CLAIM",
    "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.HEALTH_FOOD_OVER_REGISTERED_SCOPE",
    "EFFICACY_PERFORMANCE.PERFORMANCE_RESULT.EFFICACY_CLAIM_EXCEEDING_SCOPE_OR_TIME_PROMISE",
    "DISCLOSURE_WARNING.CONDITIONS_LIMITS.COSMETIC_INGREDIENT_CONCENTRATION_LABEL",
    "DISCLOSURE_WARNING.CONDITIONS_LIMITS.COSMETIC_EFFICACY_EXEMPTION_SCOPE",
    "DISCLOSURE_WARNING.STATUTORY_WARNING.STATUTORY_DISCLOSURE_NOT_PROMINENT_OR_CLEAR",
    "ENDORSEMENT.CONSENT_FOR_NAME_IMAGE",
    "ENDORSEMENT.JOINT_LIABILITY",
    "MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT",
    "MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT.MINOR_HARMFUL_CONTENT_WARNING",
    "MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT.MINOR_ACCESS_RESTRICTION_VIOLATION",
    "MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT.MINOR_LIVE_STREAM_ACCOUNT_REGISTRATION",
    "MINORS_PUBLIC_ORDER.DISCRIMINATION_INSULT.DEFAMATION_INSULT_INDIVIDUALS",
    "MATERIAL_PLATFORM.PLACEMENT_JUMP",
    "WORKFLOW_DUTY.POST_LAUNCH_FULFILLMENT",
    "WORKFLOW_DUTY.PRE_REVIEW",
}

DIRECT_REMAP = {
    "PROHIBITED_CONTENT.PROHIBITED_PRODUCTS.DISGUISED_ADVERTISING_HEALTH_WELLNESS": "DISCLOSURE_WARNING.AD_IDENTIFIABILITY.DISGUISED_AD",
    "CLAIM_EXPRESSION.AMBIGUOUS_EXAGGERATED.INSTANT_EFFECT_EXAGGERATION": "CLAIM_EXPRESSION.AMBIGUOUS_EXAGGERATED.UNVERIFIABLE_EXAGGERATED_CLAIMS",
    "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.HEALTH_FOOD_OVER_REGISTERED_SCOPE": "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.HEALTH_FOOD_FUNCTION_CLAIM_NONCOMPLIANT",
    "DISCLOSURE_WARNING.CONDITIONS_LIMITS.COSMETIC_INGREDIENT_CONCENTRATION_LABEL": "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_EFFICACY_CLAIM_NONCOMPLIANT",
    "ENDORSEMENT.CONSENT_FOR_NAME_IMAGE": "IP_PERSONALITY.PORTRAIT_NAME.UNAUTHORIZED_USE_OF_NAME_OR_IMAGE_IN_AD",
    "ENDORSEMENT.JOINT_LIABILITY": "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_CIVIL_LIABILITY",
    "WORKFLOW_DUTY.POST_LAUNCH_FULFILLMENT.FALSE_AD_CIVIL_LIABILITY": "TRUTHFULNESS.FALSE_FACT.FALSE_ADVERTISING_CIVIL_LIABILITY",
    "WORKFLOW_DUTY.PRE_REVIEW.LIVE_STREAMING_ADVERTISER_RESPONSIBILITY": "WORKFLOW_DUTY.PLATFORM_ALGORITHM.LIVE_MARKETING_AD_RESPONSIBLE_PARTY",
    "WORKFLOW_DUTY.PRE_REVIEW.LIVE_STREAMING_OPERATOR_ADVERTISER_RESPONSIBILITY": "WORKFLOW_DUTY.PLATFORM_ALGORITHM.LIVE_MARKETING_AD_RESPONSIBLE_PARTY",
    "WORKFLOW_DUTY.PRE_REVIEW.UNAUTHORIZED_MODIFICATION_AFTER_AD_REVIEW": "SCOPE_ACCESS.AD_REVIEW_ACCESS.PRE_REVIEW_APPROVAL_AND_CONTENT_CONSISTENCY",
}

MINOR_PARENTS = {
    "MINOR_INDUCEMENT_OVERCONSUMPTION": "MINORS_PUBLIC_ORDER.MINOR_PAYMENT",
    "MINOR_PAYMENT_LIMIT_CIRCUMVENTION": "MINORS_PUBLIC_ORDER.MINOR_PAYMENT",
    "MINOR_ANTI_ADDICTION_CIRCUMVENTION": "MINORS_PUBLIC_ORDER.MINOR_PAYMENT",
    "MINOR_TARGETED_ADVERTISING_IDENTIFICATION": "MINORS_PUBLIC_ORDER.AD_TARGETING_MEDIA",
    "MINOR_TARGETED_ADVERTISING_PROHIBITED_MEDIA": "MINORS_PUBLIC_ORDER.AD_TARGETING_MEDIA",
    "MINOR_SCHOOL_COMMERCIAL_ACTIVITY": "MINORS_PUBLIC_ORDER.AD_TARGETING_MEDIA",
    "MINOR_PROHIBITED_GOODS_SERVICES": "MINORS_PUBLIC_ORDER.PROHIBITED_SALES",
    "MINOR_HARMFUL_CONTENT_WARNING": "MINORS_PUBLIC_ORDER.PLATFORM_PROTECTION_DUTY",
    "MINOR_ACCESS_RESTRICTION_VIOLATION": "MINORS_PUBLIC_ORDER.PLATFORM_PROTECTION_DUTY",
    "MINOR_LIVE_STREAM_ACCOUNT_REGISTRATION": "MINORS_PUBLIC_ORDER.PLATFORM_PROTECTION_DUTY",
    "MINOR_PERSONAL_INFO_PROCESSING": "MINORS_PUBLIC_ORDER.PERSONAL_INFORMATION",
    "MINOR_HARMFUL_CONTENT_DISSEMINATION": "MINORS_PUBLIC_ORDER.DANGEROUS_BEHAVIOR",
}

MATERIAL_PARENTS = {
    "LANDING_PAGE_LINK_PLATFORM_REQUIREMENT": "MATERIAL_PLATFORM.LANDING_PAGE_JUMP",
    "LANDING_PAGE_CONTENT_IRRELEVANT": "MATERIAL_PLATFORM.LANDING_PAGE_JUMP",
    "LANDING_PAGE_PRODUCT_UNAVAILABLE_FALSE_PROMOTION": "MATERIAL_PLATFORM.LANDING_PAGE_JUMP",
    "LANDING_PAGE_JUMP_THIRD_PARTY_APP": "MATERIAL_PLATFORM.LANDING_PAGE_JUMP",
    "POPUP_INTERFERE_NORMAL_BROWSING": "MATERIAL_PLATFORM.DISPLAY_CLOSE",
    "POPUP_CLOSE_MARK_ONE_CLICK": "MATERIAL_PLATFORM.DISPLAY_CLOSE",
    "SPLASH_AD_FREQUENCY_LIMIT": "MATERIAL_PLATFORM.PLACEMENT_SPEC_FREQUENCY",
    "OUTDOOR_AD_PROHIBITED_SETTING": "MATERIAL_PLATFORM.PLACEMENT_SPEC_FREQUENCY",
    "CREATIVE_TARGETING_NETWORK_WIFI": "MATERIAL_PLATFORM.PLACEMENT_SPEC_FREQUENCY",
    "GIF_CREATIVE_PLACEMENT_GROUP": "MATERIAL_PLATFORM.PLACEMENT_SPEC_FREQUENCY",
}


def make_node(issue_id, parent_id, level, name):
    return {
        "issue_id": issue_id,
        "parent_issue_id": parent_id,
        "level": level,
        "node_type": "legal_issue" if level == 3 else "directory",
        "name": name,
        "definition": "",
        "reason": "v0.2 人工批准调整",
        "confidence": "approved",
    }


def mapping_from_row(row):
    return {
        "issue_id": row["三级问题ID"] or row["二级问题ID"],
        "rule_uid": row["规则UID"],
        "rule_title": row["规则标题"],
        "mapping_type": row["规则映射类型"] or "direct",
        "track": row["原始赛道"],
        "source_file": row["来源文件"],
        "source_type": row["来源类型"],
        "source_name": row["法规/平台规则"],
        "article": row["条款"],
        "original_text": row["规则原文"],
    }


def route_registration(item):
    text = f"{item['rule_title']} {item['original_text']}"
    if item["rule_uid"] == "RUID-1c76c8f71fb25e6a" or "特殊医学用途配方食品广告" in text:
        return "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.SPECIAL_MEDICAL_FOOD_AD_OVER_REGISTERED_SCOPE", "direct"
    if item["rule_uid"] == "RUID-644b0ca0795e37d0" or ("药品广告" in text and "说明书范围" in text):
        return "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.DRUG_AD_OVER_INSTRUCTION_SCOPE", "direct"
    if "医疗器械广告" in text and "范围" in text:
        return "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.MEDICAL_DEVICE_AD_OVER_REGISTERED_SCOPE", "direct"
    if "保健食品" in text and ("广告" in text or "标签" in text) and ("一致" in text or "范围" in text):
        return "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.HEALTH_FOOD_FUNCTION_CLAIM_NONCOMPLIANT", "direct"
    role = "fact_check" if any(word in text for word in ("提供", "公示", "证明", "资质")) else "platform_access"
    return None, role


def route_mapping(item):
    issue = item["issue_id"]
    text = f"{item['rule_title']} {item['original_text']}"
    if issue.startswith("SCOPE_ACCESS.PRODUCT_REGISTRATION"):
        return route_registration(item)
    if issue == "SCOPE_ACCESS.SCOPE_CLASSIFICATION.CROSS_CATEGORY_EFFICACY_CLAIM":
        ordinary = any(word in text for word in ("普通化妆品", "非特殊化妆品", "非特殊用途化妆品"))
        target = "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_SPECIAL_EFFICACY_CLAIM_BY_ORDINARY_PRODUCT" if ordinary else "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_EFFICACY_CLAIM_NONCOMPLIANT"
        return target, "direct"
    if issue in {
        "SCOPE_ACCESS.SUBJECT_QUALIFICATION.BRAND_NAME_NON_DISTINCTIVE_OR_NON_EXCLUSIVE",
        "SCOPE_ACCESS.SUBJECT_QUALIFICATION.HEALTH_FOOD_LICENSE_COMPLIANCE",
        "SCOPE_ACCESS.SUBJECT_QUALIFICATION.GAME_REAL_NAME_REGISTRATION_REQUIREMENT",
    }:
        return None, "platform_access"
    if issue == "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.HEALTH_FOOD_DISEASE_WORD_OR_EXAGGERATED_CLAIM":
        if any(word in text for word in ("安全", "无毒", "无害", "副作用")):
            return "EFFICACY_PERFORMANCE.SAFETY_SIDE_EFFECT.SAFETY_ABSOLUTE_GUARANTEE_CLAIM", "direct"
        if any(word in text for word in ("疾病", "治疗", "预防", "药物", "医疗", "病症")):
            return "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.DISEASE_TREATMENT_MEDICAL_CLAIM", "direct"
        return "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.HEALTH_FOOD_FALSE_OR_MISLEADING_EFFICACY_CLAIM", "direct"
    if issue == "EFFICACY_PERFORMANCE.PERFORMANCE_RESULT.EFFICACY_CLAIM_EXCEEDING_SCOPE_OR_TIME_PROMISE":
        target = "EFFICACY_PERFORMANCE.DISEASE_MEDICAL.MEDICAL_DEVICE_AD_OVER_REGISTERED_SCOPE" if "医疗器械" in text else "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_EFFICACY_CLAIM_NONCOMPLIANT"
        return target, "direct"
    if issue == "DISCLOSURE_WARNING.CONDITIONS_LIMITS.COSMETIC_EFFICACY_EXEMPTION_SCOPE":
        return "EFFICACY_PERFORMANCE.HEALTH_COSMETIC_EFFECT.COSMETIC_EFFICACY_CLAIM_NONCOMPLIANT", "exception"
    if issue == "DISCLOSURE_WARNING.STATUTORY_WARNING.STATUTORY_DISCLOSURE_NOT_PROMINENT_OR_CLEAR":
        if item["rule_uid"] in {"RUID-6003a44f5ad562ab", "RUID-9bee9296a0831ba5", "RUID-eced1eeac7b05ee5"}:
            return "__ALL_WARNING_LEAVES__", "supporting_basis"
        if "化妆品" in text:
            return "DISCLOSURE_WARNING.STATUTORY_WARNING.COSMETIC_AD_WARNING_MISSING", "direct"
        if "保健食品" in text:
            return "DISCLOSURE_WARNING.STATUTORY_WARNING.HEALTH_FOOD_WARNING_NOT_PROMINENT", "direct"
        return None, "supporting_basis"
    if issue == "CLAIM_EXPRESSION.ABSOLUTE.ABSOLUTE_SUPERLATIVE_TERMS" and any(word in text for word in ("最高", "最佳", "第一", "领先", "排名", "顶级", "国家级", "最先进", "最科学")):
        return "CLAIM_EXPRESSION.ABSOLUTE.RANKING_UNIQUENESS_TERMS", item["mapping_type"]
    if issue.startswith("CLAIM_EXPRESSION.COMPARATIVE_RANKING."):
        return issue.replace("CLAIM_EXPRESSION.COMPARATIVE_RANKING.", "CLAIM_EXPRESSION.ABSOLUTE."), item["mapping_type"]
    if issue == "CLAIM_EXPRESSION.GUARANTEE_COMMITMENT.ABSOLUTE_EFFECT_SAFETY_GUARANTEE" and "安全" not in text and any(word in text for word in ("效果", "功效", "见效", "有效")):
        return "CLAIM_EXPRESSION.GUARANTEE_COMMITMENT.EFFECT_GUARANTEE_COMMITMENT", item["mapping_type"]
    if issue.startswith("MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT."):
        suffix = issue.rsplit(".", 1)[-1]
        if suffix in {"MINOR_HARMFUL_CONTENT_WARNING", "MINOR_LIVE_STREAM_ACCOUNT_REGISTRATION"}:
            return "MINORS_PUBLIC_ORDER.PUBLIC_MORALITY.DEFAMATION_INSULT", item["mapping_type"]
        if suffix == "MINOR_ACCESS_RESTRICTION_VIOLATION":
            return "MINORS_PUBLIC_ORDER.DISCRIMINATION_INSULT.MINOR_ACCESS_RESTRICTION_VIOLATION", item["mapping_type"]
        parent = MINOR_PARENTS.get(suffix)
        if parent:
            return f"{parent}.{suffix}", item["mapping_type"]
    if issue == "MINORS_PUBLIC_ORDER.DISCRIMINATION_INSULT.DEFAMATION_INSULT_INDIVIDUALS":
        return "MINORS_PUBLIC_ORDER.PUBLIC_MORALITY.DEFAMATION_INSULT", item["mapping_type"]
    if issue == "MINORS_PUBLIC_ORDER.DISCRIMINATION_INSULT.DISPARAGEMENT_OF_COMPETITORS":
        return "CLAIM_EXPRESSION.ABSOLUTE.COMPARATIVE_RANKING_DISPARAGE_OTHERS", item["mapping_type"]
    if issue.startswith("MATERIAL_PLATFORM.PLACEMENT_JUMP."):
        suffix = issue.rsplit(".", 1)[-1]
        return f"{MATERIAL_PARENTS[suffix]}.{suffix}", item["mapping_type"]
    return DIRECT_REMAP.get(issue, issue), item["mapping_type"]


def prepare_nodes(project_root):
    nodes = []
    for raw in flatten_tree(load_combined_tree(project_root)):
        ignored = {"children", "direct_rule_uids", "number", "rule_count", "level_3_count", "child_count"}
        nodes.append({key: deepcopy(value) for key, value in raw.items() if key not in ignored})
    by_id = {node["issue_id"]: node for node in nodes}
    by_id["CLAIM_EXPRESSION.ABSOLUTE"]["name"] = "绝对化、比较、排名与唯一性宣称"
    by_id["CLAIM_EXPRESSION.GUARANTEE_COMMITMENT.ABSOLUTE_EFFECT_SAFETY_GUARANTEE"]["name"] = "产品安全性绝对保证承诺"
    by_id["TRUTHFULNESS.FABRICATED_EFFECT.REAL_PERSON_EFFECT_DISPLAY"]["name"] = "保健食品广告禁止真人展示效果"
    by_id["IP_PERSONALITY.THIRD_PARTY_AUTH"]["name"] = "授权要求"
    by_id["MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT"]["issue_id"] = "MINORS_PUBLIC_ORDER.MINOR_PAYMENT"
    by_id["MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT"]["name"] = "诱导消费与付费限制规避"
    for node in nodes:
        issue = node["issue_id"]
        if node.get("parent_issue_id") == "CLAIM_EXPRESSION.COMPARATIVE_RANKING":
            node["issue_id"] = issue.replace("CLAIM_EXPRESSION.COMPARATIVE_RANKING.", "CLAIM_EXPRESSION.ABSOLUTE.")
            node["parent_issue_id"] = "CLAIM_EXPRESSION.ABSOLUTE"
        if node.get("parent_issue_id") == "MINORS_PUBLIC_ORDER.MINOR_INDUCEMENT":
            suffix = issue.rsplit(".", 1)[-1]
            parent = MINOR_PARENTS.get(suffix)
            if parent:
                node["issue_id"] = f"{parent}.{suffix}"
                node["parent_issue_id"] = parent
        if node.get("parent_issue_id") == "MATERIAL_PLATFORM.PLACEMENT_JUMP":
            suffix = issue.rsplit(".", 1)[-1]
            parent = MATERIAL_PARENTS[suffix]
            node["issue_id"] = f"{parent}.{suffix}"
            node["parent_issue_id"] = parent
    nodes = [
        node for node in nodes
        if node["issue_id"] not in REMOVE_NODES
        and not node["issue_id"].startswith("SCOPE_ACCESS.PRODUCT_REGISTRATION.")
    ]
    nodes.extend(make_node(*spec) for spec in NEW_NODES)
    return nodes


def build_approved_assets(project_root=ROOT):
    project_root = Path(project_root)
    nodes = prepare_nodes(project_root)
    rows = load_mapping_rows(project_root)
    proactive_prefix = "ENDORSEMENT.PROACTIVE_CHECKLIST."
    proactive_rows = [
        row for row in rows
        if (row["三级问题ID"] or row["二级问题ID"]).startswith(proactive_prefix)
    ]
    if proactive_rows:
        nodes.append(make_node(
            "ENDORSEMENT.PROACTIVE_CHECKLIST",
            "ENDORSEMENT_REVIEW",
            2,
            "主动补资料核查",
        ))
        for row in proactive_rows:
            issue_id = row["三级问题ID"] or row["二级问题ID"]
            if not any(node["issue_id"] == issue_id for node in nodes):
                nodes.append(make_node(
                    issue_id,
                    "ENDORSEMENT.PROACTIVE_CHECKLIST",
                    3,
                    row["三级问题"] or row["规则标题"] or "主动补资料核查项",
                ))
    node_ids = {node["issue_id"] for node in nodes}
    warning_leaves = [
        node["issue_id"] for node in nodes
        if node.get("parent_issue_id") == "DISCLOSURE_WARNING.STATUTORY_WARNING"
        and node.get("level") == 3
    ]
    active, excluded, seen = [], [], set()
    for row in rows:
        item = mapping_from_row(row)
        original_issue = item["issue_id"]
        target, role = route_mapping(item)
        targets = warning_leaves if target == "__ALL_WARNING_LEAVES__" else [target]
        if not target:
            item.update(
                original_issue_id=original_issue,
                exclusion_role=role,
                exclusion_reason="经人工批准移出普通文案问题树，规则资产仍保留",
            )
            excluded.append(item)
            continue
        for target_id in targets:
            if target_id not in node_ids:
                raise ValueError(f"mapping target does not exist: {target_id}")
            mapped = deepcopy(item)
            mapped.update(issue_id=target_id, mapping_type=role, original_issue_id=original_issue)
            key = (target_id, mapped["rule_uid"], role)
            if key not in seen:
                seen.add(key)
                active.append(mapped)
    mapped_ids = {item["issue_id"] for item in active}
    nodes = [node for node in nodes if node.get("level") < 3 or node["issue_id"] in mapped_ids]
    valid = {node["issue_id"] for node in nodes}
    if not all(item["issue_id"] in valid and item.get("original_text") for item in active):
        raise ValueError("active mapping validation failed")
    return correct_issue_assets({
        "taxonomy": {
            "version": "v0.2-approved",
            "status": "review_snapshot",
            "source": "v0.1 + approved review decisions",
            "nodes": nodes,
        },
        "mappings": {
            "version": "v0.2-approved",
            "status": "review_snapshot",
            "mappings": active,
            "excluded_mappings": excluded,
        },
    }, project_root)


def tree_rows(nodes, mappings):
    by_id = {item["issue_id"]: item for item in nodes}
    children, rules = defaultdict(list), defaultdict(list)
    for item in nodes:
        children[item.get("parent_issue_id")].append(item)
    for item in mappings:
        rules[item["issue_id"]].append(item)
    root_rank = {root_id: position for position, root_id in enumerate(ROOT_ORDER)}
    for values in children.values():
        values.sort(key=lambda item: (root_rank.get(item["issue_id"], 999), item["issue_id"] == "MINORS_PUBLIC_ORDER.PUBLIC_MORALITY.DEFAMATION_INSULT", item.get("name", ""), item["issue_id"]))
    rows = []
    for root_id in ROOT_ORDER:
        root = by_id.get(root_id)
        if not root:
            continue
        for level_2 in children[root_id]:
            for rule in sorted(rules[level_2["issue_id"]], key=lambda item: (item["rule_uid"], item["mapping_type"])):
                rows.append((root, level_2, level_2, rule))
            level_3_nodes = children[level_2["issue_id"]] or ([level_2] if level_2.get("level") == 3 else [])
            for level_3 in level_3_nodes:
                for rule in sorted(rules[level_3["issue_id"]], key=lambda item: (item["rule_uid"], item["mapping_type"])):
                    rows.append((root, level_2, level_3, rule))
    return rows


def merge_cells(sheet, column, start, end):
    if end > start:
        sheet.merge_cells(start_row=start, start_column=column, end_row=end, end_column=column)
    sheet.cell(start, column).alignment = Alignment(vertical="center", wrap_text=True)


def export_workbook(result, output_path):
    rows = tree_rows(result["taxonomy"]["nodes"], result["mappings"]["mappings"])
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "按问题分组的规则审核"
    headers = [
        "一级问题", "二级问题", "三级问题", "规则UID", "规则标题", "映射角色",
        "来源类型", "法规或平台规则", "条款", "规则原文", "原始赛道",
        "原问题ID", "人工结论", "调整后归属", "备注",
    ]
    sheet.append(headers)
    for root, level_2, level_3, rule in rows:
        sheet.append([
            root["name"], level_2["name"], level_3["name"], rule["rule_uid"],
            rule["rule_title"], rule["mapping_type"], rule["source_type"],
            rule["source_name"], rule["article"], rule["original_text"], rule["track"],
            rule["original_issue_id"], "", "", "",
        ])
    for column in (3, 2, 1):
        start = 2
        previous = tuple(sheet.cell(start, c).value for c in range(1, column + 1))
        for row_number in range(3, sheet.max_row + 2):
            current = (
                tuple(sheet.cell(row_number, c).value for c in range(1, column + 1))
                if row_number <= sheet.max_row else None
            )
            if current != previous:
                merge_cells(sheet, column, start, row_number - 1)
                start, previous = row_number, current

    excluded_sheet = workbook.create_sheet("移出普通文案树的规则")
    excluded_headers = [
        "原问题ID", "规则UID", "规则标题", "保留角色", "移出原因",
        "来源类型", "法规或平台规则", "条款", "规则原文", "原始赛道",
    ]
    excluded_sheet.append(excluded_headers)
    for item in result["mappings"]["excluded_mappings"]:
        excluded_sheet.append([
            item["original_issue_id"], item["rule_uid"], item["rule_title"],
            item["exclusion_role"], item["exclusion_reason"], item["source_type"],
            item["source_name"], item["article"], item["original_text"], item["track"],
        ])

    guide = workbook.create_sheet("使用说明")
    guide.append(["项目", "说明"])
    for row in [
        ("版本", "v0.3 最终资产：已同步批准的问题树合并、JSONBase 修订、UID 重定向与生产召回资格门。"),
        ("direct", "规则直接支持该问题，可以作为疑似违规依据。"),
        ("supporting_basis", "总括性或上位依据，必须与具体规则共同展示，不单独生成违规结论。"),
        ("exception", "适用例外或豁免条件，供判断是否排除违规。"),
        ("移出普通文案树", "规则未删除，保留在独立 Sheet，供事实核验、准入或流程判断使用。"),
    ]:
        guide.append(row)

    header_fill = PatternFill("solid", fgColor="1F5364")
    review_fill = PatternFill("solid", fgColor="FFF2CC")
    thin = Side(style="thin", color="D9E2E5")
    for current_sheet in (sheet, excluded_sheet, guide):
        for cell in current_sheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in current_sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(bottom=thin)
        current_sheet.freeze_panes = "D2" if current_sheet is sheet else "A2"
        current_sheet.auto_filter.ref = current_sheet.dimensions
    for row in sheet.iter_rows(min_row=2, min_col=13, max_col=15):
        for cell in row:
            cell.fill = review_fill
    for index, width in enumerate([20, 27, 34, 23, 38, 17, 15, 33, 15, 78, 14, 48, 20, 28, 30], 1):
        sheet.column_dimensions[chr(64 + index)].width = width
    for index, width in enumerate([48, 23, 38, 18, 35, 15, 35, 15, 80, 14], 1):
        excluded_sheet.column_dimensions[chr(64 + index)].width = width
    guide.column_dimensions["A"].width = 24
    guide.column_dimensions["B"].width = 110
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def render_html(result):
    nodes = result["taxonomy"]["nodes"]
    mappings = result["mappings"]["mappings"]
    by_id = {item["issue_id"]: item for item in nodes}
    children, rules = defaultdict(list), defaultdict(list)
    for item in nodes:
        children[item.get("parent_issue_id")].append(item)
    for item in mappings:
        rules[item["issue_id"]].append(item)
    root_rank = {root_id: position for position, root_id in enumerate(ROOT_ORDER)}
    for values in children.values():
        values.sort(key=lambda item: (root_rank.get(item["issue_id"], 999), item["issue_id"] == "MINORS_PUBLIC_ORDER.PUBLIC_MORALITY.DEFAMATION_INSULT", item.get("name", "")))
    escape = lambda value: html.escape(str(value or ""), quote=True)
    numbers = {}

    def number_nodes(parent_id, prefix):
        for index, item in enumerate(children[parent_id], 1):
            number = f"{prefix}.{index}" if prefix else str(index)
            numbers[item["issue_id"]] = number
            number_nodes(item["issue_id"], number)

    number_nodes(None, "")

    def render_rule(rule):
        labels = {
            "direct": "直接依据",
            "supporting_basis": "辅助依据",
            "exception": "例外条款",
            "proactive_check": "补资料核查",
        }
        return (
            f'<article class="rule"><div class="rule-head"><code>{escape(rule["rule_uid"])}</code>'
            f'<strong>{escape(rule["rule_title"])}</strong><span>{escape(labels.get(rule["mapping_type"], rule["mapping_type"]))}</span></div>'
            f'<p class="source">{escape(rule["source_type"])} · {escape(rule["source_name"])} {escape(rule["article"])}</p>'
            f'<blockquote>{escape(rule["original_text"])}</blockquote></article>'
        )

    def render_node(item):
        subnodes = children[item["issue_id"]]
        direct_rules = sorted(rules[item["issue_id"]], key=lambda rule: rule["rule_uid"])
        definition = (
            f'<p class="definition"><b>问题定义：</b>{escape(item.get("definition"))}</p>'
            if item.get("definition") else ""
        )
        body = "".join(render_rule(rule) for rule in direct_rules)
        body += "".join(render_node(child) for child in subnodes)
        return (
            f'<details class="node l{item["level"]}"><summary><span class="num">{escape(numbers[item["issue_id"]])}</span>'
            f'<span class="name">{escape(item["name"])}</span><span class="count">{len(subnodes)} 个子节点 · {len(direct_rules)} 条直接规则</span>'
            f'</summary><div class="content">{definition}{body}</div></details>'
        )

    tree = "".join(render_node(by_id[root_id]) for root_id in ROOT_ORDER if root_id in by_id)
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Adsure 全部问题树 v0.3</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f7;color:#18272d;font:14px/1.65 "Microsoft YaHei",sans-serif}}header{{background:#174b5c;color:white;padding:26px 5vw}}h1{{margin:0;font-size:27px;letter-spacing:0}}header p{{margin:4px 0 0;color:#dcecef}}main{{max-width:1420px;margin:auto;padding:18px 24px 50px}}.tools{{position:sticky;top:0;z-index:5;display:flex;gap:8px;padding:10px;background:#fff;border:1px solid #d8e2e5}}input{{flex:1;min-width:180px;padding:9px;border:1px solid #b8c8ce}}button{{padding:8px 13px;border:1px solid #91abb4;background:#fff;cursor:pointer}}.tree{{margin-top:12px;background:#fff;border:1px solid #d8e2e5;padding:14px}}details{{border-left:1px solid #d9e2e5;margin-left:18px}}details.l1{{margin:0;border-left:0;border-bottom:1px solid #dfe7e9}}summary{{display:flex;align-items:center;gap:9px;padding:10px;cursor:pointer}}summary:hover{{background:#edf5f6}}.num{{color:#176079;font-weight:700;min-width:50px}}.name{{font-weight:600;font-size:15px}}.l1>summary .name{{font-size:19px;color:#174b5c}}.count{{margin-left:auto;color:#667980;font-size:12px}}.content{{padding:0 9px 8px 22px}}.definition{{background:#f4f8f9;border-left:3px solid #8db2bd;padding:9px 12px}}.rule{{border:1px solid #dbe3e5;margin:9px 0;padding:11px;background:#fff}}.rule-head{{display:flex;gap:9px;align-items:center;flex-wrap:wrap}}.rule-head code{{color:#14566b}}.rule-head span{{background:#eaf3f5;color:#174b5c;padding:2px 7px;font-size:12px}}.source{{color:#5d7077;margin:6px 0}}blockquote{{margin:0;padding:9px 12px;background:#f8fafb;border-left:3px solid #c3d2d7;white-space:pre-wrap}}.hidden{{display:none}}@media(max-width:720px){{main{{padding:10px}}.count{{width:100%;margin-left:59px}}summary{{flex-wrap:wrap}}.content{{padding-left:8px}}}}
</style></head><body><header><h1>广告合规问题树与规则溯源</h1><p>v0.3 · 已同步批准的目录合并、JSONBase 修订、UID 重定向、例外与辅助依据角色</p></header><main><div class="tools"><input id="search" placeholder="搜索问题、规则 UID、规则标题或原文"><button id="expand">全部展开</button><button id="collapse">全部收起</button></div><section class="tree">{tree}</section></main><script>
const details=[...document.querySelectorAll('details')];document.getElementById('expand').onclick=()=>details.forEach(x=>x.open=true);document.getElementById('collapse').onclick=()=>details.forEach(x=>x.open=false);document.getElementById('search').oninput=e=>{{const q=e.target.value.trim().toLowerCase();details.forEach(x=>x.classList.remove('hidden'));if(!q)return;details.forEach(x=>{{if(!x.textContent.toLowerCase().includes(q))x.classList.add('hidden');else{{x.open=true;let p=x.parentElement.closest('details');while(p){{p.classList.remove('hidden');p.open=true;p=p.parentElement.closest('details')}}}}}})}};
</script></body></html>'''


def write_outputs(result, output_dir=OUTPUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        output_dir / "approved_issue_taxonomy_v0.2.json",
        output_dir / "approved_rule_issue_mapping_v0.2.json",
        output_dir / "问题-规则对应关系人工审核表_v0.2.xlsx",
        output_dir / "全部问题树_一级二级三级关系_v0.2.html",
    ]
    paths[0].write_text(json.dumps(result["taxonomy"], ensure_ascii=False, indent=2), encoding="utf-8")
    paths[1].write_text(json.dumps(result["mappings"], ensure_ascii=False, indent=2), encoding="utf-8")
    export_workbook(result, paths[2])
    paths[3].write_text(render_html(result), encoding="utf-8", newline="\n")
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    result = build_approved_assets(args.project_root)
    paths = write_outputs(result, args.output_dir)
    print(json.dumps({
        "nodes": len(result["taxonomy"]["nodes"]),
        "active_mappings": len(result["mappings"]["mappings"]),
        "excluded_mappings": len(result["mappings"]["excluded_mappings"]),
        "unique_active_rules": len({item["rule_uid"] for item in result["mappings"]["mappings"]}),
        "outputs": [str(path) for path in paths],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
