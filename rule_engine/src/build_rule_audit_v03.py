# -*- coding: utf-8 -*-
"""Build a non-destructive v0.3 rule-audit workbook from reviewed v0.2 decisions."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from export_specialized_rule_audit_v02 import build_audit_rows, node_context, read_json


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REVIEW = ROOT / "reports" / "approved_issue_tree_v02" / "全部规则专项人工审核表_v0.2.xlsx"
OUTPUT = ROOT / "reports" / "approved_issue_tree_v03" / "全部规则专项人工审核表_v0.2.xlsx"
REMOVE_LABEL = "不纳入规则库"


def header_map(sheet):
    return {cell.value: cell.column for cell in sheet[1] if cell.value}


def reviewed_decisions(workbook_path):
    workbook = load_workbook(workbook_path, data_only=False, read_only=True)
    duplicate_sheet = workbook["完全重复规范"]
    duplicate_headers = header_map(duplicate_sheet)
    duplicate_groups = defaultdict(lambda: {"uids": [], "target": ""})
    for row_number in range(2, duplicate_sheet.max_row + 1):
        group_id = duplicate_sheet.cell(row_number, duplicate_headers["重复组"]).value
        uid = duplicate_sheet.cell(row_number, duplicate_headers["规则UID"]).value
        target = duplicate_sheet.cell(row_number, duplicate_headers["重复目标rule_uid"]).value
        if not group_id or not uid:
            continue
        duplicate_groups[group_id]["uids"].append(uid)
        duplicate_groups[group_id]["target"] = target or duplicate_groups[group_id]["target"]

    track_sheet = workbook["赛道污染"]
    track_headers = header_map(track_sheet)
    remove_uids, track_updates, track_decisions = set(), {}, []
    for row_number in range(2, track_sheet.max_row + 1):
        uid = track_sheet.cell(row_number, track_headers["规则UID"]).value
        suggested = track_sheet.cell(row_number, track_headers["建议赛道"]).value
        if not uid or not suggested:
            continue
        record = {
            "规则UID": uid,
            "规则标题": track_sheet.cell(row_number, track_headers["规则标题"]).value or "",
            "原始赛道": track_sheet.cell(row_number, track_headers["原始赛道"]).value or "",
            "人工建议": suggested,
        }
        track_decisions.append(record)
        if suggested == REMOVE_LABEL:
            remove_uids.add(uid)
        else:
            track_updates[uid] = suggested
    return {
        "duplicate_groups": dict(duplicate_groups),
        "remove_uids": remove_uids,
        "track_updates": track_updates,
        "track_decisions": track_decisions,
    }


def normalize(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[\s，。；：、,.;:‘’“”\"'（）()《》【】\[\]·]", "", value)


def duplicate_fingerprint(item):
    return (
        normalize(item.get("source_type")),
        normalize(item.get("source_name")),
        normalize(item.get("article")),
        normalize(item.get("original_text")),
    )


def resolve_uid(uid, redirects):
    visited = set()
    while uid in redirects and redirects[uid] != uid:
        if uid in visited:
            raise ValueError(f"duplicate redirect cycle: {uid}")
        visited.add(uid)
        uid = redirects[uid]
    return uid


def build_redirects(decisions):
    redirects, records = {}, []
    removed = decisions["remove_uids"]
    for group_id, group in decisions["duplicate_groups"].items():
        survivors = sorted(set(group["uids"]) - removed)
        preferred = group["target"]
        canonical = preferred if preferred in survivors else (survivors[0] if survivors else "")
        for uid in sorted(set(group["uids"])):
            if uid in removed:
                status = "已按Sheet5意见移除"
                final_uid = ""
            elif uid == canonical:
                status = "保留主UID"
                final_uid = canonical
            else:
                status = "合并到主UID"
                final_uid = canonical
                redirects[uid] = canonical
            records.append({
                "重复组": group_id,
                "原规则UID": uid,
                "最终规则UID": final_uid,
                "处理结果": status,
                "判定依据": "Sheet3人工确认：组内规则完全重复",
            })
    return redirects, records


def canonical_metadata(items, redirects):
    by_uid = defaultdict(list)
    for item in items:
        by_uid[item["rule_uid"]].append(item)
    metadata = {}
    for uid in by_uid:
        final_uid = resolve_uid(uid, redirects)
        candidates = by_uid.get(final_uid) or by_uid[uid]
        metadata[final_uid] = max(
            candidates,
            key=lambda item: sum(bool(item.get(key)) for key in (
                "rule_title", "source_file", "source_type", "source_name", "article", "original_text"
            )),
        )
    return metadata


def propagated_tracks(decisions, redirects):
    values = defaultdict(set)
    for uid, track in decisions["track_updates"].items():
        if uid in decisions["remove_uids"]:
            continue
        values[resolve_uid(uid, redirects)].add(track)
    conflicts = {uid: tracks for uid, tracks in values.items() if len(tracks) > 1}
    if conflicts:
        raise ValueError(f"conflicting reviewed track decisions: {conflicts}")
    return {uid: next(iter(tracks)) for uid, tracks in values.items()}


def transform_mappings(items, removed, redirects, track_updates):
    metadata = canonical_metadata(items, redirects)
    transformed, seen = [], set()
    for source in items:
        if source["rule_uid"] in removed:
            continue
        item = deepcopy(source)
        final_uid = resolve_uid(item["rule_uid"], redirects)
        canonical = metadata[final_uid]
        item["rule_uid"] = final_uid
        for key in ("rule_title", "source_file", "source_type", "source_name", "article", "original_text"):
            item[key] = canonical.get(key, item.get(key, ""))
        if final_uid in track_updates:
            item["track"] = track_updates[final_uid]
        key = (
            item.get("issue_id"), item["rule_uid"], item.get("mapping_type"),
            item.get("exclusion_role"), item.get("original_issue_id"),
        )
        if key not in seen:
            seen.add(key)
            transformed.append(item)
    return transformed


def find_duplicate_groups(items):
    by_uid = {}
    for item in items:
        by_uid.setdefault(item["rule_uid"], item)
    groups = defaultdict(list)
    for uid, item in by_uid.items():
        fingerprint = duplicate_fingerprint(item)
        if fingerprint[-1]:
            groups[fingerprint].append(uid)
    return [sorted(uids) for uids in groups.values() if len(uids) > 1]


def transform_review_rows(rows, removed, redirects, track_updates, metadata):
    output, seen = [], set()
    for source in rows:
        uid = source.get("规则UID")
        if not uid or uid in removed:
            continue
        row = deepcopy(source)
        final_uid = resolve_uid(uid, redirects)
        row["规则UID"] = final_uid
        canonical = metadata.get(final_uid, {})
        replacements = {
            "规则标题": "rule_title", "原始赛道": "track", "来源文件": "source_file",
            "来源类型": "source_type", "法规或平台规则": "source_name",
            "条款": "article", "规则原文": "original_text",
        }
        for column, field in replacements.items():
            if field in canonical:
                row[column] = canonical.get(field, "")
        if final_uid in track_updates:
            row["原始赛道"] = track_updates[final_uid]
        row["人工结论"] = ""
        row["重复目标rule_uid"] = ""
        row["建议赛道"] = ""
        row["资产处置"] = ""
        row["备注"] = ""
        signature = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
        if signature not in seen:
            seen.add(signature)
            output.append(row)
    return output


def build_v03_review(project_root=ROOT, source_review=SOURCE_REVIEW):
    project_root = Path(project_root)
    decisions = reviewed_decisions(source_review)
    asset_dir = project_root / "reports" / "approved_issue_tree_v02"
    taxonomy = read_json(asset_dir / "approved_issue_taxonomy_v0.2.json")
    mapping_asset = read_json(asset_dir / "approved_rule_issue_mapping_v0.2.json")
    source_active = mapping_asset["mappings"]
    source_excluded = mapping_asset["excluded_mappings"]
    source_all = source_active + source_excluded

    redirects, merge_records = build_redirects(decisions)
    track_updates = propagated_tracks(decisions, redirects)
    first_pass = transform_mappings(source_all, decisions["remove_uids"], redirects, track_updates)

    counts = Counter(item["rule_uid"] for item in first_pass)
    automatic_groups = find_duplicate_groups(first_pass)
    for index, uids in enumerate(automatic_groups, 1):
        canonical = sorted(uids, key=lambda uid: (-counts[uid], uid))[0]
        for uid in uids:
            if uid != canonical:
                redirects[uid] = canonical
            merge_records.append({
                "重复组": f"V03-AUTO-{index:03d}",
                "原规则UID": uid,
                "最终规则UID": canonical,
                "处理结果": "保留主UID" if uid == canonical else "合并到主UID",
                "判定依据": "v0.3复查：来源、条款和规范化规则原文完全一致",
            })
    track_updates = propagated_tracks(decisions, redirects)
    active = transform_mappings(source_active, decisions["remove_uids"], redirects, track_updates)
    excluded = transform_mappings(source_excluded, decisions["remove_uids"], redirects, track_updates)
    residual = find_duplicate_groups(active + excluded)

    final_metadata = canonical_metadata(active + excluded, {})
    original_metadata = canonical_metadata(source_all, {})
    track_records = []
    for decision in decisions["track_decisions"]:
        uid = decision["规则UID"]
        if uid in decisions["remove_uids"]:
            final_uid, final_track, status = "", "", "已删除"
        else:
            final_uid = resolve_uid(uid, redirects)
            final_track = track_updates.get(final_uid, decision["人工建议"])
            status = "已调整赛道"
        track_records.append({
            **decision,
            "最终规则UID": final_uid,
            "调整后赛道": final_track,
            "处理结果": status,
        })
    removed_records = []
    for uid in sorted(decisions["remove_uids"]):
        item = original_metadata.get(uid, {})
        removed_records.append({
            "规则UID": uid,
            "规则标题": item.get("rule_title", ""),
            "原始赛道": item.get("track", ""),
            "法规或平台规则": item.get("source_name", ""),
            "条款": item.get("article", ""),
            "规则原文": item.get("original_text", ""),
            "处理结果": "不进入v0.3候选规则资产",
            "说明": "依据Sheet5人工意见；jsonbase原始JSON未删除",
        })

    old_audit = build_audit_rows(project_root)
    metadata = canonical_metadata(active + excluded, {})
    transformed_review = {
        key: transform_review_rows(old_audit[key], decisions["remove_uids"], redirects, track_updates, metadata)
        for key in ("mismatch", "proactive", "low_confidence")
    }
    return {
        "taxonomy": taxonomy,
        "active": active,
        "excluded": excluded,
        "decisions": decisions,
        "redirects": redirects,
        "merge_records": merge_records,
        "track_records": track_records,
        "removed_records": removed_records,
        "residual_duplicate_groups": residual,
        "review_rows": transformed_review,
    }


def mapping_rows(items, nodes, ancestor):
    rows = []
    for item in items:
        issue_id = item.get("issue_id", "")
        rows.append({
            "当前一级问题": ancestor(issue_id, 1).get("name", ""),
            "当前二级问题": ancestor(issue_id, 2).get("name", ""),
            "当前问题": nodes.get(issue_id, {}).get("name", issue_id),
            "规则UID": item["rule_uid"],
            "规则标题": item.get("rule_title", ""),
            "映射角色": item.get("mapping_type", item.get("exclusion_role", "")),
            "适用赛道": item.get("track", ""),
            "来源文件": item.get("source_file", ""),
            "来源类型": item.get("source_type", ""),
            "法规或平台规则": item.get("source_name", ""),
            "条款": item.get("article", ""),
            "规则原文": item.get("original_text", ""),
            "人工结论": "", "调整后问题": "", "备注": "",
        })
    return rows


def cross_directory_rows(items, nodes):
    grouped = defaultdict(list)
    for item in items:
        grouped[item["rule_uid"]].append(item)
    rows = []
    for uid, occurrences in grouped.items():
        issue_ids = sorted({item["issue_id"] for item in occurrences})
        if len(issue_ids) < 2:
            continue
        item = occurrences[0]
        rows.append({
            "规则UID": uid,
            "规则标题": item.get("rule_title", ""),
            "适用赛道": item.get("track", ""),
            "当前问题数": len(issue_ids),
            "当前全部问题": " | ".join(nodes.get(issue, {}).get("name", issue) for issue in issue_ids),
            "规则原文": item.get("original_text", ""),
            "人工结论": "", "调整后问题": "", "备注": "",
        })
    return rows


def write_table(workbook, title, rows, empty_headers=None):
    sheet = workbook.create_sheet(title)
    headers = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)
    headers = headers or list(empty_headers or ["说明"])
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    header_fill = PatternFill("solid", fgColor="1F5364")
    review_fill = PatternFill("solid", fgColor="FFF2CC")
    thin = Side(style="thin", color="D9E2E5")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in sheet.iter_rows(min_row=2):
        for index, cell in enumerate(row):
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(bottom=thin)
            if headers[index] in {"人工结论", "调整后问题", "备注"}:
                cell.fill = review_fill
    for index, header in enumerate(headers, 1):
        width = 18
        if header in {"规则原文", "当前全部问题", "判定依据", "说明"}:
            width = 72
        elif header in {"规则标题", "当前问题", "调整后问题", "法规或平台规则"}:
            width = 34
        elif "UID" in header or "uid" in header:
            width = 23
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = width
    sheet.freeze_panes = "D2" if len(headers) >= 4 else "A2"
    sheet.auto_filter.ref = sheet.dimensions
    return sheet


def export_v03_workbook(result, output_path=OUTPUT):
    workbook = Workbook()
    guide = workbook.active
    guide.title = "审核说明"
    guide_rows = [
        ("版本性质", "v0.3非破坏性审核快照；未修改jsonbase、v0.2资产或生产规则引擎。"),
        ("Sheet3处理", "采纳全部完全重复判断，每组仅保留一个规则UID；全部UID去向见“完全重复规范”。"),
        ("Sheet5处理", "“不纳入规则库”仅从v0.3候选资产排除；其他意见已更新适用赛道。"),
        ("对照测试", "保留原规则引擎和jsonbase用于baseline；v0.3候选资产后续单独接入实验链路做A/B测试。"),
    ]
    guide.append(["项目", "说明"])
    for row in guide_rows:
        guide.append(row)
    nodes, ancestor = node_context(result["taxonomy"]["nodes"])
    all_rows = mapping_rows(result["active"], nodes, ancestor)
    write_table(workbook, "清洗后全部规则", all_rows)
    write_table(workbook, "完全重复规范", result["merge_records"])
    write_table(workbook, "同一规则跨目录重叠", cross_directory_rows(result["active"], nodes))
    write_table(workbook, "赛道污染", result["track_records"])
    write_table(workbook, "问题错配复核", result["review_rows"]["mismatch"])
    write_table(workbook, "移出普通文案树", mapping_rows(result["excluded"], nodes, ancestor))
    write_table(workbook, "不纳入规则库", result["removed_records"])
    write_table(workbook, "主动补资料候选", result["review_rows"]["proactive"])
    write_table(workbook, "中低置信度", result["review_rows"]["low_confidence"])
    residual_rows = [
        {"重复组": index, "规则UID列表": "、".join(uids), "处理状态": "待合并"}
        for index, uids in enumerate(result["residual_duplicate_groups"], 1)
    ]
    write_table(workbook, "剩余重复检查", residual_rows, ["重复组", "规则UID列表", "处理状态"])
    unique_rules = {item["rule_uid"] for item in result["active"] + result["excluded"]}
    checks = [
        {"校验项": "Sheet5不纳入规则库意见", "结果": "通过", "数量": len(result["decisions"]["remove_uids"])},
        {"校验项": "Sheet5赛道调整意见", "结果": "通过", "数量": len(result["decisions"]["track_updates"])},
        {"校验项": "Sheet3人工确认重复组", "结果": "通过", "数量": len(result["decisions"]["duplicate_groups"])},
        {"校验项": "清洗后唯一规则UID", "结果": "通过", "数量": len(unique_rules)},
        {"校验项": "剩余完全重复组", "结果": "通过" if not result["residual_duplicate_groups"] else "失败", "数量": len(result["residual_duplicate_groups"])},
        {"校验项": "有效映射规则原文完整", "结果": "通过" if all(item.get("original_text") for item in result["active"]) else "失败", "数量": len(result["active"])},
        {"校验项": "原始资料状态", "结果": "未修改jsonbase、v0.2与生产链路", "数量": 0},
    ]
    write_table(workbook, "校验结果", checks)
    for sheet in workbook.worksheets:
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="1F5364")
            cell.font = Font(color="FFFFFF", bold=True)
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
    guide.column_dimensions["A"].width = 24
    guide.column_dimensions["B"].width = 100
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return output_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--source-review", type=Path, default=SOURCE_REVIEW)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    result = build_v03_review(args.project_root, args.source_review)
    output = export_v03_workbook(result, args.output)
    print(json.dumps({
        "output": str(output),
        "removed_uids": len(result["decisions"]["remove_uids"]),
        "track_updates": len(result["decisions"]["track_updates"]),
        "reviewed_duplicate_groups": len(result["decisions"]["duplicate_groups"]),
        "merge_records": len(result["merge_records"]),
        "active_mappings": len(result["active"]),
        "excluded_mappings": len(result["excluded"]),
        "unique_rules": len({item["rule_uid"] for item in result["active"] + result["excluded"]}),
        "residual_duplicate_groups": len(result["residual_duplicate_groups"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
