# -*- coding: utf-8 -*-
"""Label rules with recall.trigger_layer.

The label separates ordinary ad-copy recall from rules that should be triggered
by fact fields or workflow nodes:

- content: ad copy/content violation
- fact: fact, proof, filing, qualification, or materials verification
- workflow: subject obligation, platform responsibility, archive/process duty

DeepSeek is optional and is only used for low-confidence or conflicting
heuristic results when --use-deepseek is provided.
"""

import argparse
import csv
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from deepseek_client import DeepSeekClient, DeepSeekClientError


PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_JSONBASE_DIR = PROJECT_BASE / "jsonbase"
DEFAULT_REPORT_DIR = PROJECT_BASE / "reports" / "trigger_layer"
PROMPT_VERSION = "trigger_layer_label_v1_20260714"

ALLOWED_LAYERS = {"content", "fact", "workflow"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}


CONTENT_TERMS = [
    "绝对化",
    "最高级",
    "最佳",
    "第一",
    "顶级",
    "虚假",
    "引人误解",
    "误导",
    "欺骗",
    "夸大",
    "医疗",
    "疾病",
    "治疗",
    "疗效",
    "功效",
    "宣称",
    "宣传",
    "广告可识别",
    "未标广告",
    "软文",
    "种草",
    "诱导点击",
    "弹窗",
    "一键关闭",
    "未成年人",
    "代言",
    "贬低",
    "竞品",
    "比较",
    "价格",
    "促销",
    "赠品",
    "限时",
    "免费",
    "明示",
    "显著",
    "清晰",
    "显著标明",
    "处方药",
    "烟草广告",
    "酒类广告",
    "饮酒",
    "驾驶",
    "动作",
    "公共场所",
    "大众传播媒介",
    "保健功能",
    "替代药物",
    "普通食品",
    "化妆品",
    "概率承诺",
    "抽奖",
    "充值诱导",
]

FACT_TERMS = [
    "备案",
    "备案号",
    "注册证",
    "批准文号",
    "许可证",
    "许可",
    "资质",
    "蓝帽",
    "专利号",
    "专利",
    "检测报告",
    "检验报告",
    "证明材料",
    "证明文件",
    "证明",
    "销量证明",
    "排名依据",
    "获奖证明",
    "认证证书",
    "审查批准",
    "广告审查",
    "批准文件",
    "概率公示",
    "软著",
    "版号",
    "批件",
    "功效依据",
    "数据来源",
    "科研成果",
    "统计资料",
    "调查结果",
    "后台数据",
    "备案核查",
]

WORKFLOW_SUBJECT_TERMS = [
    "广告主",
    "广告经营者",
    "广告发布者",
    "互联网信息服务提供者",
    "平台",
    "平台经营者",
    "电子商务经营者",
]

WORKFLOW_DUTY_TERMS = [
    "平台责任",
    "平台义务",
    "主体责任",
    "发布者责任",
    "经营者责任",
    "广告档案",
    "档案",
    "保存",
    "留存",
    "查验",
    "核对",
    "审核制度",
    "承接登记",
    "投放记录",
    "算法推荐",
    "监测",
    "投诉举报",
    "断开链接",
    "配合调查",
    "身份信息",
    "管理制度",
    "记录保存",
    "审核人员",
]

FACT_FIELD_HINTS = [
    "filing",
    "license",
    "qualification",
    "certificate",
    "approval",
    "permit",
    "patent",
    "report",
    "proof",
    "record",
    "registration",
    "版号",
    "软著",
    "备案",
    "资质",
    "证明",
    "报告",
    "批准",
    "许可",
]


def _compact(value, max_chars=8000):
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[:max_chars] + "...[truncated]"
    return text


def _rule_text(rule):
    recall = rule.get("recall", {}) or {}
    detection = rule.get("detection", {}) or {}
    keyword_signals = detection.get("keyword_signals", {}) or {}
    parts = [
        rule.get("rule_uid"),
        rule.get("rule_id"),
        rule.get("title"),
        rule.get("dimension"),
        rule.get("source_type"),
        rule.get("platform"),
        rule.get("industry"),
        rule.get("risk_level"),
        _compact(rule.get("applies_to", {}), 1200),
        _compact(rule.get("preconditions", {}), 1200),
        _compact(keyword_signals, 1800),
        _compact(detection.get("semantic_criteria", ""), 1000),
        _compact(detection.get("decision", ""), 1000),
        _compact(recall.get("tags", []), 1000),
        recall.get("vector_text"),
        recall.get("semantic_reason"),
        _compact(rule.get("legal_attention", {}), 1200),
        _compact(rule.get("routing", {}), 800),
    ]
    for item in rule.get("legal_basis", []) or []:
        parts.append(_compact(item, 1500))
    return " ".join(str(part) for part in parts if part)


def _primary_text(rule):
    recall = rule.get("recall", {}) or {}
    return " ".join(
        str(part)
        for part in [
            rule.get("title"),
            rule.get("dimension"),
            _compact(rule.get("preconditions", {}), 1000),
            _compact(rule.get("detection", {}).get("keyword_signals", {}), 1000),
            _compact(recall.get("tags", []), 700),
            recall.get("vector_text"),
            recall.get("semantic_reason"),
        ]
        if part
    )


def _hits(text, terms):
    return [term for term in terms if term and term.lower() in text.lower()]


def _required_field_hints(rule):
    fields = rule.get("preconditions", {}).get("required_context_fields", []) or []
    joined = " ".join(str(item) for item in fields)
    return _hits(joined, FACT_FIELD_HINTS)


def _score_rule(rule):
    primary = _primary_text(rule)
    full = _rule_text(rule)
    primary_content = _hits(primary, CONTENT_TERMS)
    primary_fact = _hits(primary, FACT_TERMS)
    full_content = _hits(full, CONTENT_TERMS)
    full_fact = _hits(full, FACT_TERMS)
    workflow_subject_hits = _hits(full, WORKFLOW_SUBJECT_TERMS)
    workflow_duty_primary_hits = _hits(primary, WORKFLOW_DUTY_TERMS)
    workflow_duty_full_hits = _hits(full, WORKFLOW_DUTY_TERMS)
    field_hints = _required_field_hints(rule)

    content_score = len(primary_content) * 3 + len(set(full_content))
    fact_score = len(primary_fact) * 3 + len(set(full_fact)) + len(field_hints) * 4
    workflow_score = len(workflow_duty_primary_hits) * 3 + len(set(workflow_duty_full_hits))
    if workflow_subject_hits and workflow_duty_full_hits:
        workflow_score += 4

    title_dim = f"{rule.get('title') or ''} {rule.get('dimension') or ''}"
    if _hits(title_dim, ["平台责任", "平台义务", "档案", "记录保存", "主体责任"]):
        workflow_score += 5
    if _hits(title_dim, ["备案", "资质", "批准文号", "许可证", "证明材料", "证明文件", "版号", "软著"]):
        fact_score += 5
    if _hits(title_dim, ["虚假", "引人误解", "绝对化", "宣称", "广告可识别", "诱导", "功效", "治疗"]):
        content_score += 5

    return {
        "content_score": content_score,
        "fact_score": fact_score,
        "workflow_score": workflow_score,
        "content_hits": sorted(set(primary_content + full_content))[:12],
        "fact_hits": sorted(set(primary_fact + full_fact + field_hints))[:12],
        "workflow_hits": sorted(set(workflow_subject_hits + workflow_duty_primary_hits + workflow_duty_full_hits))[:12],
    }


def classify_rule_heuristic(rule):
    """Return trigger-layer label with reason/confidence/source."""

    scores = _score_rule(rule)
    content_score = scores["content_score"]
    fact_score = scores["fact_score"]
    workflow_score = scores["workflow_score"]

    candidates = [
        ("content", content_score),
        ("fact", fact_score),
        ("workflow", workflow_score),
    ]
    candidates.sort(key=lambda item: item[1], reverse=True)
    layer, top_score = candidates[0]
    second_layer, second_score = candidates[1]
    conflict = second_score > 0 and top_score - second_score <= 3

    if top_score <= 0:
        return {
            "trigger_layer": "content",
            "reason": "No strong layer signal was found; defaulted to content for MVP content-audit recall and flagged for review.",
            "confidence": "low",
            "source": "heuristic",
            "scores": scores,
            "conflict": False,
        }
    if layer == "workflow" and workflow_score < 4:
        return {
            "trigger_layer": "content",
            "reason": "Only weak workflow wording was found; defaulted to content for MVP content-audit recall and flagged for review.",
            "confidence": "low",
            "source": "heuristic",
            "scores": scores,
            "conflict": False,
        }

    # Keep ad-copy prohibitions in content even when the legal basis mentions
    # proof or advertiser responsibility.
    title_dim = f"{rule.get('title') or ''} {rule.get('dimension') or ''}"
    content_title = bool(_hits(title_dim, ["虚假", "引人误解", "绝对化", "宣称", "广告可识别", "诱导", "功效", "治疗"]))
    if content_title and content_score >= 5 and workflow_score < content_score + 6:
        layer = "content"
        top_score = content_score
        second_layer, second_score = max(
            [("fact", fact_score), ("workflow", workflow_score)], key=lambda item: item[1]
        )
        conflict = second_score > 0 and top_score - second_score <= 3

    confidence = "high"
    if conflict:
        confidence = "medium"
    if top_score < 5:
        confidence = "low"
    elif top_score < 8 and conflict:
        confidence = "low"

    if layer == "content":
        hit_text = "、".join(scores["content_hits"][:5]) or "content signal"
        reason = f"Rule is mainly triggered by ad-copy wording or content risk signals: {hit_text}."
    elif layer == "fact":
        hit_text = "、".join(scores["fact_hits"][:5]) or "fact signal"
        reason = f"Rule mainly depends on filing, qualification, proof, data, or materials verification: {hit_text}."
    else:
        hit_text = "、".join(scores["workflow_hits"][:5]) or "workflow signal"
        reason = f"Rule mainly concerns subject obligation, platform responsibility, archive, or process duty: {hit_text}."

    if conflict:
        reason += f" It also has {second_layer} signals, so this should be reviewed."

    return {
        "trigger_layer": layer,
        "reason": reason,
        "confidence": confidence,
        "source": "heuristic",
        "scores": scores,
        "conflict": conflict,
    }


def _needs_deepseek(result):
    return result.get("confidence") == "low" or bool(result.get("conflict"))


def _deepseek_payload(rule, heuristic):
    fields = {
        "rule_uid": rule.get("rule_uid"),
        "rule_id": rule.get("rule_id"),
        "serial_no": rule.get("serial_no"),
        "title": rule.get("title"),
        "dimension": rule.get("dimension"),
        "source_type": rule.get("source_type"),
        "platform": rule.get("platform"),
        "risk_level": rule.get("risk_level"),
        "applies_to": rule.get("applies_to", {}),
        "preconditions": rule.get("preconditions", {}),
        "detection": rule.get("detection", {}),
        "recall": rule.get("recall", {}),
        "routing": rule.get("routing", {}),
        "legal_attention": rule.get("legal_attention", {}),
        "legal_basis": [
            {
                "source_id": item.get("source_id"),
                "article": item.get("article"),
                "role": item.get("role"),
                "text": _compact(item.get("text", ""), 900),
            }
            for item in (rule.get("legal_basis", []) or [])
        ],
        "heuristic_result": heuristic,
    }
    return fields


SYSTEM_PROMPT = """你是资深广告合规法务与规则引擎标注员。你的任务不是判断某条广告文案是否违规，而是判断规则应由哪一层机制触发。严格只返回 JSON。"""


def _user_prompt(rule, heuristic):
    return """请给这条广告合规规则标注 recall.trigger_layer。

字段定义：
- content：文案内容违规。适合由广告文案本身通过关键词、正则、语义召回触发。
- fact：事实/资料核验。适合由文案中的事实主张 + 上下文字段/备案/资质/证明材料状态触发。
- workflow：主体义务/平台责任/档案流程。适合由审核任务类型、流程节点、平台责任或档案保存义务触发，不适合进入普通文案召回池。

判断原则：
1. 看这条规则命中时，真实触发源来自文案、事实资料，还是流程/主体义务。
2. 内容表述禁止类、虚假宣传、绝对化、医疗功效、诱导点击等通常为 content。
3. 备案、资质、批准文号、检测报告、证明材料、版号、软著、概率公示等通常为 fact。
4. 平台责任、广告档案、查验核对、保存记录、投诉处理、算法推荐记录、广告经营者/发布者义务通常为 workflow。
5. 如果一条规则同时涉及事实和文案，但主要是禁止在广告中作某种表述，优先 content；如果主要是要求核验证据或材料，优先 fact。

严格返回：
{
  "trigger_layer": "content/fact/workflow",
  "reason": "一句话说明为什么这样分层",
  "confidence": "low/medium/high"
}

规则 JSON：
""" + json.dumps(_deepseek_payload(rule, heuristic), ensure_ascii=False, indent=2)


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def classify_rule_deepseek(rule, heuristic, client):
    response = client.create_chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(rule, heuristic)},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = response["choices"][0]["message"]["content"]
    data = _extract_json(content)
    layer = str(data.get("trigger_layer", "")).strip()
    confidence = str(data.get("confidence", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if layer not in ALLOWED_LAYERS:
        raise ValueError(f"Invalid trigger_layer from DeepSeek: {layer}")
    if confidence not in ALLOWED_CONFIDENCE:
        raise ValueError(f"Invalid confidence from DeepSeek: {confidence}")
    if not reason:
        raise ValueError("Missing reason from DeepSeek.")
    return {
        "trigger_layer": layer,
        "reason": reason,
        "confidence": confidence,
        "source": "deepseek",
        "scores": heuristic.get("scores", {}),
        "conflict": heuristic.get("conflict", False),
    }


def _rules_from_data(data):
    if isinstance(data, dict):
        rules = data.get("rules", [])
        return rules if isinstance(rules, list) else []
    if isinstance(data, list):
        return data
    return []


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _backup_file(path, stamp):
    backup = path.with_name(path.name + f".bak_{stamp}")
    shutil.copy2(path, backup)
    return backup


def _apply_result(rule, result, labeled_at):
    recall = rule.setdefault("recall", {})
    recall["trigger_layer"] = result["trigger_layer"]
    recall["trigger_layer_reason"] = result["reason"]
    recall["trigger_layer_confidence"] = result["confidence"]
    recall["trigger_layer_source"] = result["source"]
    recall["trigger_layer_labeled_at"] = labeled_at
    recall["trigger_layer_prompt_version"] = PROMPT_VERSION


def _existing_result(rule):
    recall = rule.get("recall", {}) or {}
    layer = recall.get("trigger_layer")
    if layer not in ALLOWED_LAYERS:
        return None
    return {
        "trigger_layer": layer,
        "reason": recall.get("trigger_layer_reason", ""),
        "confidence": recall.get("trigger_layer_confidence", "medium"),
        "source": recall.get("trigger_layer_source", "existing"),
        "scores": {},
        "conflict": False,
    }


def _new_summary(args, timestamp):
    return {
        "prompt_version": PROMPT_VERSION,
        "timestamp": timestamp,
        "jsonbase_dir": str(args.jsonbase_dir),
        "dry_run": bool(args.dry_run),
        "overwrite": bool(args.overwrite),
        "use_deepseek": bool(args.use_deepseek),
        "files_seen": 0,
        "files_changed": 0,
        "rules_seen": 0,
        "rules_labeled": 0,
        "rules_skipped_existing": 0,
        "rules_failed": 0,
        "counts_by_layer": {"content": 0, "fact": 0, "workflow": 0},
        "counts_by_confidence": {"high": 0, "medium": 0, "low": 0},
        "counts_by_source": {},
        "low_confidence_count": 0,
        "conflict_count": 0,
    }


def _bump(mapping, key):
    mapping[key] = mapping.get(key, 0) + 1


def label_jsonbase(args):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    labeled_at = datetime.now().isoformat(timespec="seconds")
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / f"{timestamp}_trigger_layer_log.jsonl"
    csv_path = report_dir / f"{timestamp}_trigger_layer_report.csv"
    summary_path = report_dir / f"{timestamp}_trigger_layer_summary.json"
    low_conf_path = report_dir / f"{timestamp}_trigger_layer_low_confidence.json"

    summary = _new_summary(args, timestamp)
    low_confidence_items = []
    client = None
    if args.use_deepseek:
        client = DeepSeekClient(timeout=args.timeout)

    files = sorted(Path(args.jsonbase_dir).rglob("*.json"))
    if args.limit_files:
        files = files[: args.limit_files]

    processed_limit = 0
    with log_path.open("w", encoding="utf-8") as log_file, csv_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "file",
                "rule_uid",
                "rule_id",
                "serial_no",
                "title",
                "trigger_layer",
                "confidence",
                "source",
                "conflict",
                "changed",
                "reason",
                "error",
            ],
        )
        writer.writeheader()

        for path in files:
            summary["files_seen"] += 1
            try:
                data = _load_json(path)
            except Exception as exc:
                entry = {"file": str(path), "status": "file_error", "error": str(exc)}
                log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                summary["rules_failed"] += 1
                continue

            rules = _rules_from_data(data)
            file_changed = False
            for rule in rules:
                if args.limit_rules and processed_limit >= args.limit_rules:
                    break
                processed_limit += 1
                summary["rules_seen"] += 1
                entry = {
                    "file": str(path.relative_to(PROJECT_BASE) if path.is_relative_to(PROJECT_BASE) else path),
                    "rule_uid": rule.get("rule_uid"),
                    "rule_id": rule.get("rule_id"),
                    "serial_no": rule.get("serial_no"),
                    "title": rule.get("title"),
                    "changed": False,
                    "error": "",
                }
                try:
                    existing = None if args.overwrite else _existing_result(rule)
                    if existing:
                        result = existing
                        summary["rules_skipped_existing"] += 1
                    else:
                        heuristic = classify_rule_heuristic(rule)
                        result = heuristic
                        if args.use_deepseek and _needs_deepseek(heuristic):
                            try:
                                result = classify_rule_deepseek(rule, heuristic, client)
                                if args.sleep:
                                    time.sleep(args.sleep)
                            except (DeepSeekClientError, ValueError, KeyError, json.JSONDecodeError) as exc:
                                result = heuristic
                                result["reason"] = result["reason"] + f" DeepSeek fallback used because: {exc}"
                        if not args.dry_run:
                            _apply_result(rule, result, labeled_at)
                            file_changed = True
                            entry["changed"] = True
                        summary["rules_labeled"] += 1

                    layer = result["trigger_layer"]
                    confidence = result["confidence"]
                    source = result["source"]
                    summary["counts_by_layer"][layer] += 1
                    summary["counts_by_confidence"][confidence] += 1
                    _bump(summary["counts_by_source"], source)
                    if confidence == "low":
                        summary["low_confidence_count"] += 1
                    if result.get("conflict"):
                        summary["conflict_count"] += 1
                    if confidence == "low" or result.get("conflict"):
                        low_confidence_items.append(
                            {
                                **entry,
                                "trigger_layer": layer,
                                "confidence": confidence,
                                "source": source,
                                "reason": result["reason"],
                                "scores": result.get("scores", {}),
                                "conflict": result.get("conflict", False),
                            }
                        )
                    entry.update(
                        {
                            "status": "ok",
                            "trigger_layer": layer,
                            "confidence": confidence,
                            "source": source,
                            "reason": result["reason"],
                            "conflict": result.get("conflict", False),
                        }
                    )
                except Exception as exc:
                    summary["rules_failed"] += 1
                    entry.update({"status": "failed", "error": str(exc)})

                log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                writer.writerow(
                    {
                        "file": entry.get("file"),
                        "rule_uid": entry.get("rule_uid"),
                        "rule_id": entry.get("rule_id"),
                        "serial_no": entry.get("serial_no"),
                        "title": entry.get("title"),
                        "trigger_layer": entry.get("trigger_layer", ""),
                        "confidence": entry.get("confidence", ""),
                        "source": entry.get("source", ""),
                        "conflict": entry.get("conflict", ""),
                        "changed": entry.get("changed", ""),
                        "reason": entry.get("reason", ""),
                        "error": entry.get("error", ""),
                    }
                )

            if file_changed:
                summary["files_changed"] += 1
                if not args.dry_run:
                    _backup_file(path, timestamp)
                    _write_json(path, data)
            if args.limit_rules and processed_limit >= args.limit_rules:
                break

    summary["summary_path"] = str(summary_path)
    summary["log_path"] = str(log_path)
    summary["csv_path"] = str(csv_path)
    summary["low_confidence_path"] = str(low_conf_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    low_conf_path.write_text(json.dumps(low_confidence_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_args():
    parser = argparse.ArgumentParser(description="Label recall.trigger_layer for jsonbase rules.")
    parser.add_argument("--jsonbase-dir", type=Path, default=DEFAULT_JSONBASE_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--use-deepseek", action="store_true")
    parser.add_argument("--limit-rules", type=int, default=0)
    parser.add_argument("--limit-files", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def main():
    args = parse_args()
    summary = label_jsonbase(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
