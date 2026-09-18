# -*- coding: utf-8 -*-
"""Use DeepSeek to pre-review each UID task, then export a human verification workbook."""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from deepseek_client import DeepSeekClient
from export_parallel_rule_review_workbench_v01 import build_parallel_review_rows


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "approved_issue_tree_v03" / "规则并行审核工作台_v0.1.xlsx"
OUTPUT = ROOT / "reports" / "approved_issue_tree_v03" / "规则并行审核工作台_DeepSeek预审_v0.2.xlsx"
CHECKPOINT = ROOT / "reports" / "approved_issue_tree_v03" / "deepseek_pre_review_v0.2_checkpoint.json"
PROMPT_VERSION = "rule_uid_pre_review_v02_20260916"

TRACKS = {"通用", "游戏", "美妆", "保健食品"}
ROLES = {"direct", "supporting_basis", "exception", "proactive_check"}
ROUTES = {"普通文案召回", "fact_check", "proactive_check", "workflow_reference", "platform_access"}
DISPOSITIONS = {"保留", "调整映射", "转旁路资产", "不纳入候选资产", "待讨论"}
CONFIDENCE = {"high", "medium", "low"}

AI_FIELDS = [
    "AI建议适用赛道", "AI建议保留问题ID", "AI建议删除问题ID",
    "AI建议最终映射角色", "AI建议最终审核链路", "AI建议资产处置",
    "AI建议提交争议池", "AI置信度", "AI判断理由", "AI人工复核重点",
    "AI模型与提示词版本",
]


def response_json(response):
    content = response["choices"][0]["message"]["content"]
    if isinstance(content, dict):
        return content
    text = str(content).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    return json.loads(text)


def parse_ids(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[\n,，、]+", str(value or "")) if item.strip()]


def validate_review(payload, expected_uid, current_issue_ids, allowed_issue_ids):
    required = {
        "rule_uid", "suggested_track", "keep_issue_ids", "remove_issue_ids",
        "mapping_role", "audit_route", "asset_disposition", "submit_dispute",
    }
    missing = required - set(payload)
    if missing:
        raise ValueError(f"missing fields: {sorted(missing)}")
    if payload["rule_uid"] != expected_uid:
        raise ValueError("rule_uid mismatch")
    keep = parse_ids(payload["keep_issue_ids"])
    remove = parse_ids(payload["remove_issue_ids"])
    unknown = (set(keep) | set(remove)) - set(allowed_issue_ids)
    if unknown:
        raise ValueError("unknown issue: " + ", ".join(sorted(unknown)))
    if not set(remove) <= set(current_issue_ids):
        raise ValueError("remove_issue_ids must be current mappings")
    if set(keep) & set(remove):
        raise ValueError("keep and remove issue IDs overlap")
    if not keep and payload["submit_dispute"] is not True:
        raise ValueError("empty keep_issue_ids requires submit_dispute=true")
    if payload["suggested_track"] not in TRACKS:
        raise ValueError("invalid suggested_track")
    if payload["mapping_role"] not in ROLES:
        raise ValueError("invalid mapping_role")
    if payload["audit_route"] not in ROUTES:
        raise ValueError("invalid audit_route")
    if payload["asset_disposition"] not in DISPOSITIONS:
        raise ValueError("invalid asset_disposition")
    if not isinstance(payload["submit_dispute"], bool):
        raise ValueError("submit_dispute must be boolean")
    if payload["confidence"] not in CONFIDENCE:
        raise ValueError("invalid confidence")
    return {
        "AI建议适用赛道": payload["suggested_track"],
        "AI建议保留问题ID": "\n".join(keep),
        "AI建议删除问题ID": "\n".join(remove),
        "AI建议最终映射角色": payload["mapping_role"],
        "AI建议最终审核链路": payload["audit_route"],
        "AI建议资产处置": payload["asset_disposition"],
        "AI建议提交争议池": "是" if payload["submit_dispute"] else "否",
        "AI置信度": payload["confidence"],
        "AI判断理由": str(payload["reason"]).strip(),
        "AI人工复核重点": str(payload["human_review_focus"]).strip(),
        "AI模型与提示词版本": f"deepseek-chat / {PROMPT_VERSION}",
    }


def build_prompt(row, issue_candidates):
    rule = {
        key: row.get(key, "") for key in (
            "规则UID", "规则标题", "当前适用赛道", "当前全部问题",
            "当前全部问题ID", "当前映射角色", "来源类型", "法规或平台规则",
            "条款", "规则原文", "风险标签", "模型置信度", "历史判断理由",
        )
    }
    return f"""你是广告合规规则资产审核员。请严格依据给出的规则原文，对一个规则UID做预审。

重要口径：
1. legal_issue 是早期加工阶段“规则已映射到法律问题节点”的过渡状态，只表示问题树映射关系，不能作为最终角色。
2. 最终 mapping_role 只能选：direct、supporting_basis、exception、proactive_check。
3. direct：规则可直接支持个案疑似违规；supporting_basis：仅为原则或上位辅助依据；exception：豁免或排除条件；proactive_check：需要额外事实、资质或证明核验，不是违规结论。
4. audit_route 只能选：普通文案召回、fact_check、proactive_check、workflow_reference、platform_access。
5. 仅凭文案可以初步判断的走普通文案召回；必须核验事实真伪或第三方资料的走 fact_check；内容层可正常但投放前应主动补验的走 proactive_check；发布审核或履约流程走 workflow_reference；行业、账户或类目准入走 platform_access。
6. 只能从候选问题中选择问题ID。没有合适问题时 keep_issue_ids 为空、asset_disposition=待讨论、submit_dispute=true，禁止创造ID。
7. remove_issue_ids 只能来自当前问题ID。保留多个问题必须逐个被规则原文直接支持，否则应删除多余映射。
8. 不得因旧目录、旧赛道、规则标题或模型历史理由而覆盖规则原文。法律依据和事实不得自由编造。
9. “不纳入候选资产”仅在规则与通用广告及游戏、美妆、保健食品三个赛道均无关，且无旁路价值时选择，并必须 submit_dispute=true。

待审规则：
{json.dumps(rule, ensure_ascii=False, indent=2)}

允许选择的问题目录：
{json.dumps(issue_candidates, ensure_ascii=False, indent=2)}

只返回一个JSON对象，字段必须完整：
{{
  "rule_uid": "原样返回规则UID",
  "suggested_track": "通用|游戏|美妆|保健食品",
  "keep_issue_ids": ["允许的问题ID"],
  "remove_issue_ids": ["当前问题ID中需要解除的ID"],
  "mapping_role": "direct|supporting_basis|exception|proactive_check",
  "audit_route": "普通文案召回|fact_check|proactive_check|workflow_reference|platform_access",
  "asset_disposition": "保留|调整映射|转旁路资产|不纳入候选资产|待讨论",
  "submit_dispute": true,
  "confidence": "high|medium|low",
  "reason": "具体说明原文适用对象、规制行为、问题归属、角色、链路和处置理由",
  "human_review_focus": "指出人工最需要核对的一到两个不确定点；没有则写无"
}}"""


def issue_catalog(taxonomy):
    nodes = {node["issue_id"]: node for node in taxonomy["nodes"]}

    def root_id(issue_id):
        current = nodes.get(issue_id)
        if not current:
            parts = str(issue_id or "").split(".")
            for length in range(len(parts) - 1, 0, -1):
                current = nodes.get(".".join(parts[:length]))
                if current:
                    break
        while current and current.get("parent_issue_id"):
            current = nodes.get(current["parent_issue_id"])
        return current.get("issue_id") if current else ""

    leaves_by_root = defaultdict(list)
    for node in taxonomy["nodes"]:
        if node.get("level") == 3:
            leaves_by_root[root_id(node["issue_id"])].append({
                "issue_id": node["issue_id"],
                "name": node.get("name", ""),
                "definition": node.get("definition", ""),
            })
    return nodes, leaves_by_root, root_id


def candidates_for_row(row, nodes, leaves_by_root, root_id):
    current_ids = parse_ids(row.get("当前全部问题ID"))
    roots = {root_id(issue_id) for issue_id in current_ids if root_id(issue_id)}
    candidates = []
    for root in sorted(roots):
        candidates.extend(leaves_by_root[root])
    known = {item["issue_id"] for item in candidates}
    for issue_id in current_ids:
        if issue_id in nodes and issue_id not in known:
            node = nodes[issue_id]
            candidates.append({
                "issue_id": issue_id,
                "name": node.get("name", ""),
                "definition": node.get("definition", ""),
            })
    return candidates


def load_checkpoint(path):
    path = Path(path)
    if not path.exists():
        return {"prompt_version": PROMPT_VERSION, "reviews": {}, "errors": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("checkpoint prompt version mismatch")
    return data


def save_checkpoint(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def call_review(client, row, candidates, attempts=3):
    messages = [
        {"role": "system", "content": "你只做基于原文和给定目录的规则资产审核，并严格输出JSON。"},
        {"role": "user", "content": build_prompt(row, candidates)},
    ]
    last_error = None
    allowed_ids = {item["issue_id"] for item in candidates}
    current_ids = set(parse_ids(row.get("当前全部问题ID")))
    for attempt in range(attempts):
        try:
            response = client.create_chat_completion(
                messages=messages,
                model="deepseek-chat",
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            payload = response_json(response)
            return validate_review(payload, row["规则UID"], current_ids, allowed_ids), payload
        except Exception as exc:
            last_error = exc
            if "payload" in locals():
                messages.extend([
                    {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                    {"role": "user", "content": (
                        f"门禁失败：{exc}。你使用了无效或已移除的问题ID。"
                        "请只从下列现行ID中重选；若没有合适项，keep_issue_ids返回空数组、"
                        "asset_disposition设为待讨论且submit_dispute设为true。禁止重复旧ID或创造ID。\n"
                        + json.dumps(sorted(allowed_ids), ensure_ascii=False)
                    )},
                ])
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"DeepSeek review failed after {attempts} attempts: {last_error}")


def run_reviews(project_root=ROOT, checkpoint_path=CHECKPOINT, workers=5, limit=None):
    project_root = Path(project_root)
    workbench = build_parallel_review_rows(project_root)
    rows = workbench["rows"][:limit] if limit else workbench["rows"]
    taxonomy_path = project_root / "reports" / "approved_issue_tree_v02" / "approved_issue_taxonomy_v0.2.json"
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    nodes, leaves_by_root, root_id = issue_catalog(taxonomy)
    checkpoint = load_checkpoint(checkpoint_path)
    pending = [row for row in rows if row["规则UID"] not in checkpoint["reviews"]]
    if not pending:
        return workbench, checkpoint

    def task(row):
        candidates = candidates_for_row(row, nodes, leaves_by_root, root_id)
        return row["规则UID"], call_review(DeepSeekClient(timeout=120), row, candidates)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(task, row): row["规则UID"] for row in pending}
        for future in as_completed(futures):
            uid = futures[future]
            try:
                completed_uid, (mapped, raw) = future.result()
                checkpoint["reviews"][completed_uid] = {"mapped": mapped, "raw": raw}
                checkpoint["errors"].pop(completed_uid, None)
            except Exception as exc:
                checkpoint["errors"][uid] = str(exc)
            save_checkpoint(checkpoint_path, checkpoint)
    return workbench, checkpoint


def add_review_dropdown(sheet):
    headers = {cell.value: cell.column for cell in sheet[1] if cell.value}
    if "人工复核AI结论" not in headers or sheet.max_row < 2:
        return
    validation = DataValidation(type="list", formula1='"全部准确,部分准确,不准确,需讨论"', allow_blank=True)
    sheet.add_data_validation(validation)
    column = sheet.cell(1, headers["人工复核AI结论"]).column_letter
    validation.add(f"{column}2:{column}{sheet.max_row}")


def export_reviewed_workbench(source, output, checkpoint):
    if checkpoint.get("errors"):
        raise ValueError(f"cannot export with DeepSeek errors: {len(checkpoint['errors'])}")
    workbook = load_workbook(source)
    sheet_names = ["并行审核主表", "任务包A", "任务包B", "任务包C"]
    model_fill = PatternFill("solid", fgColor="DDEBF7")
    human_fill = PatternFill("solid", fgColor="FFF2CC")
    for sheet_name in sheet_names:
        sheet = workbook[sheet_name]
        headers = {cell.value: cell.column for cell in sheet[1] if cell.value}
        insertion = headers["审核状态"]
        sheet.insert_cols(insertion, len(AI_FIELDS) + 1)
        for offset, field in enumerate(AI_FIELDS):
            cell = sheet.cell(1, insertion + offset, field)
            cell.fill = PatternFill("solid", fgColor="2F75B5")
            cell.font = Font(color="FFFFFF", bold=True)
        human_review_column = insertion + len(AI_FIELDS)
        cell = sheet.cell(1, human_review_column, "人工复核AI结论")
        cell.fill = PatternFill("solid", fgColor="BF9000")
        cell.font = Font(color="FFFFFF", bold=True)
        uid_column = headers["规则UID"]
        for row_number in range(2, sheet.max_row + 1):
            uid = sheet.cell(row_number, uid_column).value
            review = (checkpoint["reviews"].get(uid) or {}).get("mapped")
            if not review:
                continue
            for offset, field in enumerate(AI_FIELDS):
                target = sheet.cell(row_number, insertion + offset, review[field])
                target.fill = model_fill
                target.alignment = Alignment(vertical="top", wrap_text=True)
            sheet.cell(row_number, human_review_column).fill = human_fill
        widths = [18, 48, 48, 22, 24, 22, 18, 13, 72, 55, 34, 18]
        for offset, width in enumerate(widths):
            sheet.column_dimensions[sheet.cell(1, insertion + offset).column_letter].width = width
        add_review_dropdown(sheet)
        sheet.auto_filter.ref = sheet.dimensions

    guide = workbook["操作说明"]
    guide.append(["DeepSeek预审", "蓝色列为DeepSeek建议；黄色“人工复核AI结论”选择全部准确、部分准确、不准确或需讨论。人工修正仍填写右侧原有黄色字段。"])
    guide.append(["legal_issue口径", "legal_issue仅表示早期规则与问题节点已建立映射，是待细分的过渡状态；本轮模型将其细分为direct、supporting_basis、exception或proactive_check。"])
    guide.append(["审核方式", "模型建议不能自动写回资产。选择全部准确时无需重复撰写完整结论；部分准确或不准确时，只填写有差异的人工修正字段并说明理由。"])
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    workbench, checkpoint = run_reviews(args.project_root, args.checkpoint, args.workers, args.limit)
    expected = len(workbench["rows"]) if args.limit is None else min(args.limit, len(workbench["rows"]))
    if len(checkpoint["reviews"]) < expected or checkpoint["errors"]:
        print(json.dumps({
            "status": "incomplete", "expected": expected,
            "completed": len(checkpoint["reviews"]), "errors": checkpoint["errors"],
        }, ensure_ascii=False, indent=2))
        return 2
    output = export_reviewed_workbench(args.source, args.output, checkpoint)
    print(json.dumps({
        "status": "complete", "output": str(output),
        "reviewed_uids": len(checkpoint["reviews"]),
        "model": "deepseek-chat", "prompt_version": PROMPT_VERSION,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
