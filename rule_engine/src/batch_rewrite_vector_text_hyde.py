# -*- coding: utf-8 -*-
"""Rewrite recall.vector_text with HyDE-style simulated violation text.

The script updates jsonbase rule files in place, but keeps the change narrowly
scoped to semantic recall fields:

- recall.vector_text
- recall.semantic_reason
- recall.hyde_review metadata/recommendations

semantic_enabled and semantic_role are recorded as recommendations by default.
They are only applied when --apply-semantic-recommendations is provided.
"""

import argparse
import json
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from deepseek_client import DeepSeekClient, DeepSeekClientError


PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_JSONBASE_DIR = PROJECT_BASE / "jsonbase"
DEFAULT_REPORT_DIR = PROJECT_BASE / "reports" / "semantic_recall_hyde"
PROMPT_VERSION = "hyde_vector_text_rewrite_v1_20260714"

ALLOWED_ROLES = {"primary", "fallback", "disabled"}
MAX_VECTOR_TEXT_CHARS = 50


SYSTEM_PROMPT = """你是资深广告合规规则工程师，负责把规则库中的语义召回文本改写为 HyDE 风格的“仿真违规文案集合”。

你的任务不是判断具体广告是否违规，也不是重写法条，而是为每条规则生成更适合向量召回的 recall.vector_text。

核心原则：
1. vector_text 必须像真实违规广告文案、违规表达、营销话术、软性规避表述的集合。
2. 不要写成法条解释、规则摘要、合规说明或“不得……应当……”句式。
3. 优先覆盖同一规则可能出现的多种说法、同义表达、行业场景表达和规避表达。
4. 对硬词规则，可以堆叠高频词、近义词、夸张词、短语。
5. 对开放概念规则，要生成真实广告中可能出现的语义场景，比如效果夸大、误导点击、软文种草、虚构背书等。
6. 对强事实核验、资质备案、平台责任、程序义务类规则，语义召回应谨慎；如果文案侧难以直接召回，建议 disabled 或 fallback。
7. 不要编造不存在的法律依据；只能基于输入规则内容生成召回文本。

严格只返回 JSON，不要返回 Markdown。"""


def _clip_vector_text(text, max_chars=MAX_VECTOR_TEXT_CHARS):
    text = re.sub(r"\s+", "", str(text or "")).strip()
    return text[:max_chars]


def _compact(value, max_chars=1200):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) if not isinstance(value, str) else value
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...[truncated]"


def _rule_payload(rule):
    legal_basis = []
    for item in rule.get("legal_basis", []) or []:
        legal_basis.append(
            {
                "source_id": item.get("source_id"),
                "article": item.get("article"),
                "role": item.get("role"),
                "text": _compact(item.get("text", ""), 700),
            }
        )

    detection = rule.get("detection", {}) or {}
    recall = rule.get("recall", {}) or {}
    return {
        "rule_uid": rule.get("rule_uid"),
        "rule_id": rule.get("rule_id"),
        "serial_no": rule.get("serial_no"),
        "title": rule.get("title"),
        "dimension": rule.get("dimension"),
        "risk_level": rule.get("risk_level"),
        "source_type": rule.get("source_type"),
        "platform": rule.get("platform"),
        "industry": rule.get("industry"),
        "applies_to": rule.get("applies_to", {}),
        "preconditions": rule.get("preconditions", {}),
        "legal_basis": legal_basis,
        "detection": {
            "method": detection.get("method"),
            "keyword_signals": detection.get("keyword_signals", {}),
            "semantic_criteria": detection.get("semantic_criteria"),
            "decision": detection.get("decision"),
        },
        "recall": {
            "tags": recall.get("tags", []),
            "vector_text": recall.get("vector_text", ""),
            "semantic_enabled": recall.get("semantic_enabled"),
            "semantic_role": recall.get("semantic_role"),
            "semantic_reason": recall.get("semantic_reason"),
        },
        "examples": rule.get("examples", {}),
        "legal_attention": rule.get("legal_attention", {}),
    }


def _user_prompt(rule):
    return """请对下面这条广告合规规则生成 HyDE 风格的语义召回改写建议。

输出要求：
{
  "vector_text": "用于替换 recall.vector_text 的 HyDE 风格文本。必须像真实违规广告文案/违规表达集合，不要写法条解释。",
  "semantic_reason": "一句话说明为什么这条规则适合或不适合语义召回，以及该 vector_text 的召回意图。",
  "semantic_enabled_recommendation": true,
  "semantic_role_recommendation": "primary/fallback/disabled",
  "tags_recommendation": ["可选，3-8个短标签"],
  "negative_signals_recommendation": ["可选，容易误召回时建议排除的信号"],
  "change_summary": "一句话说明本次改写相较原 vector_text 的变化",
  "confidence": "low/medium/high"
}

字段解释：
- primary：关键词难以覆盖，语义召回应作为主要召回方式。
- fallback：关键词/正则优先，语义召回只做兜底。
- disabled：不建议进入语义召回，通常是程序义务、主体责任、备案资质、纯事实核验或非文案内容规则。

规则 JSON：
""" + json.dumps(_rule_payload(rule), ensure_ascii=False, indent=2)


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


def _validate_result(result):
    if not isinstance(result, dict):
        raise ValueError("DeepSeek result is not a JSON object.")
    vector_text = _clip_vector_text(result.get("vector_text") or "")
    result["vector_text"] = vector_text
    semantic_reason = str(result.get("semantic_reason") or "").strip()
    role = str(result.get("semantic_role_recommendation") or "").strip()
    enabled = result.get("semantic_enabled_recommendation")
    if not vector_text:
        raise ValueError("Missing vector_text.")
    if not semantic_reason:
        raise ValueError("Missing semantic_reason.")
    if role and role not in ALLOWED_ROLES:
        raise ValueError(f"Invalid semantic_role_recommendation: {role}")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("semantic_enabled_recommendation must be true/false.")
    return result


def _fallback_result(rule, error):
    recall = rule.get("recall", {}) or {}
    detection = rule.get("detection", {}) or {}
    keyword_signals = detection.get("keyword_signals", {}) or {}
    examples = rule.get("examples", {}) or {}
    parts = []
    for key in ("violation", "??", "bad"):
        value = examples.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    for key in ("hit_terms", "context_signals"):
        value = keyword_signals.get(key) or []
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
    tags = recall.get("tags") or []
    if isinstance(tags, list):
        parts.extend(str(item) for item in tags if item)
    if recall.get("vector_text"):
        parts.append(str(recall.get("vector_text")))
    seen = []
    for item in parts:
        item = item.strip()
        if item and item not in seen:
            seen.append(item)
    vector_text = _clip_vector_text("?".join(seen) or str(rule.get("title") or rule.get("dimension") or "????????"))
    return {
        "vector_text": vector_text,
        "semantic_reason": "DeepSeek ?????????????????????????? vector_text ???? HyDE ?????",
        "semantic_enabled_recommendation": recall.get("semantic_enabled"),
        "semantic_role_recommendation": recall.get("semantic_role") or "fallback",
        "tags_recommendation": tags if isinstance(tags, list) else [],
        "negative_signals_recommendation": [],
        "change_summary": f"fallback_after_deepseek_error: {error}",
        "confidence": "low",
        "fallback_used": True,
    }


def _call_deepseek(client, rule, temperature, max_retries=2):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(rule)},
    ]
    last_error = None
    for attempt in range(max_retries + 1):
        response = client.create_chat_completion(
            messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response["choices"][0]["message"]["content"]
        try:
            return _validate_result(_extract_json(content))
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON. Error: "
                        f"{exc}. Return the result again as exactly one valid JSON object. "
                        "All string values must be single-line; do not put raw line breaks inside strings.\n\n"
                        "Rule JSON:\n"
                        + json.dumps(_rule_payload(rule), ensure_ascii=False, indent=2)
                    ),
                },
            ]
    raise ValueError(f"DeepSeek returned invalid JSON after retries: {last_error}")


def _iter_rule_files(jsonbase_dir):
    for path in sorted(Path(jsonbase_dir).rglob("*.json")):
        if path.name.startswith("."):
            continue
        yield path


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rules_from_payload(payload):
    if isinstance(payload, dict) and isinstance(payload.get("rules"), list):
        return payload["rules"]
    return []


def _already_reviewed(rule, overwrite):
    if overwrite:
        return False
    recall = rule.get("recall") or {}
    review = recall.get("hyde_review") or {}
    vector_text = str(recall.get("vector_text") or "")
    normalized = re.sub(r"\s+", "", vector_text).strip()
    if len(normalized) > MAX_VECTOR_TEXT_CHARS:
        return False
    return review.get("prompt_version") == PROMPT_VERSION


def _should_process_rule(rule):
    recall = rule.get("recall", {}) or {}
    trigger_layer = recall.get("trigger_layer") or "content"
    semantic_role = recall.get("semantic_role") or "fallback"
    return (
        trigger_layer == "content"
        and recall.get("semantic_enabled") is True
        and semantic_role != "disabled"
    )


def _skip_reason(rule):
    recall = rule.get("recall", {}) or {}
    trigger_layer = recall.get("trigger_layer") or "content"
    semantic_role = recall.get("semantic_role") or "fallback"
    if trigger_layer != "content":
        return f"trigger_layer:{trigger_layer}"
    if recall.get("semantic_enabled") is not True:
        return "semantic_enabled_not_true"
    if semantic_role == "disabled":
        return "semantic_role_disabled"
    return "not_eligible"




def _backup_file(path, timestamp):
    backup = Path(str(path) + f".bak_{timestamp}")
    shutil.copy2(path, backup)
    return backup


def _write_json(path, payload):
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _update_rule(rule, result, apply_semantic_recommendations=False):
    recall = rule.setdefault("recall", {})
    old_vector_text = recall.get("vector_text")
    old_semantic_reason = recall.get("semantic_reason")
    old_enabled = recall.get("semantic_enabled")
    old_role = recall.get("semantic_role")

    recall["vector_text"] = _clip_vector_text(result["vector_text"])
    recall["semantic_reason"] = str(result["semantic_reason"]).strip()

    enabled_rec = result.get("semantic_enabled_recommendation")
    role_rec = result.get("semantic_role_recommendation")
    if apply_semantic_recommendations:
        if isinstance(enabled_rec, bool):
            recall["semantic_enabled"] = enabled_rec
        if role_rec in ALLOWED_ROLES:
            recall["semantic_role"] = role_rec

    recall["hyde_review"] = {
        "prompt_version": PROMPT_VERSION,
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "old_vector_text": old_vector_text,
        "old_semantic_reason": old_semantic_reason,
        "semantic_enabled_before": old_enabled,
        "semantic_role_before": old_role,
        "semantic_enabled_recommendation": enabled_rec,
        "semantic_role_recommendation": role_rec,
        "tags_recommendation": result.get("tags_recommendation", []),
        "negative_signals_recommendation": result.get("negative_signals_recommendation", []),
        "change_summary": result.get("change_summary"),
        "confidence": result.get("confidence"),
        "semantic_recommendations_applied": bool(apply_semantic_recommendations),
    }


def _log_line(handle, item):
    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    handle.flush()


def run(args):
    jsonbase_dir = Path(args.jsonbase_dir)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = report_dir / f"{timestamp}_hyde_vector_text_rewrite_log.jsonl"
    summary_path = report_dir / f"{timestamp}_hyde_vector_text_rewrite_summary.json"

    client = None if args.dry_run else DeepSeekClient(model=args.model, timeout=args.timeout)

    stats = {
        "prompt_version": PROMPT_VERSION,
        "jsonbase_dir": str(jsonbase_dir),
        "dry_run": args.dry_run,
        "overwrite": args.overwrite,
        "apply_semantic_recommendations": args.apply_semantic_recommendations,
        "files_seen": 0,
        "files_changed": 0,
        "rules_seen": 0,
        "rules_processed": 0,
        "rules_skipped": 0,
        "rules_skipped_by_filter": 0,
        "rules_failed": 0,
        "log_path": str(log_path),
    }

    processed_limit = args.limit_rules if args.limit_rules and args.limit_rules > 0 else None
    file_limit = args.limit_files if args.limit_files and args.limit_files > 0 else None

    limit_reached = False
    with log_path.open("w", encoding="utf-8") as log:
        for file_index, path in enumerate(_iter_rule_files(jsonbase_dir), start=1):
            if file_limit and file_index > file_limit:
                break
            stats["files_seen"] += 1
            payload = _load_json(path)
            rules = _rules_from_payload(payload)
            changed = False

            for rule_index, rule in enumerate(rules):
                if processed_limit and stats["rules_processed"] >= processed_limit:
                    limit_reached = True
                    break
                stats["rules_seen"] += 1
                rule_id = rule.get("rule_id")
                rule_uid = rule.get("rule_uid")
                if not _should_process_rule(rule):
                    stats["rules_skipped"] += 1
                    stats["rules_skipped_by_filter"] += 1
                    _log_line(
                        log,
                        {
                            "status": "skipped_filter",
                            "file": str(path),
                            "rule_id": rule_id,
                            "rule_uid": rule_uid,
                            "reason": _skip_reason(rule),
                        },
                    )
                    continue
                if _already_reviewed(rule, args.overwrite):
                    stats["rules_skipped"] += 1
                    _log_line(
                        log,
                        {
                            "status": "skipped_existing",
                            "file": str(path),
                            "rule_id": rule_id,
                            "rule_uid": rule_uid,
                        },
                    )
                    continue
                if processed_limit and stats["rules_processed"] >= processed_limit:
                    continue

                try:
                    if args.dry_run:
                        result = {
                            "vector_text": ((rule.get("recall") or {}).get("vector_text") or ""),
                            "semantic_reason": ((rule.get("recall") or {}).get("semantic_reason") or ""),
                            "semantic_enabled_recommendation": ((rule.get("recall") or {}).get("semantic_enabled")),
                            "semantic_role_recommendation": ((rule.get("recall") or {}).get("semantic_role") or "fallback"),
                            "tags_recommendation": ((rule.get("recall") or {}).get("tags") or []),
                            "negative_signals_recommendation": [],
                            "change_summary": "dry-run only; no DeepSeek call.",
                            "confidence": "medium",
                        }
                    else:
                        result = _call_deepseek(client, rule, args.temperature, max_retries=args.max_retries)
                        time.sleep(max(args.sleep, 0))

                    if not args.dry_run:
                        _update_rule(rule, result, apply_semantic_recommendations=args.apply_semantic_recommendations)
                        changed = True

                    stats["rules_processed"] += 1
                    _log_line(
                        log,
                        {
                            "status": "processed",
                            "file": str(path),
                            "rule_id": rule_id,
                            "rule_uid": rule_uid,
                            "semantic_enabled_recommendation": result.get("semantic_enabled_recommendation"),
                            "semantic_role_recommendation": result.get("semantic_role_recommendation"),
                            "vector_text_preview": str(result.get("vector_text", ""))[:120],
                        },
                    )
                except (DeepSeekClientError, ValueError, json.JSONDecodeError, KeyError) as exc:
                    if args.fallback_on_error and not args.dry_run:
                        result = _fallback_result(rule, exc)
                        _update_rule(rule, result, apply_semantic_recommendations=args.apply_semantic_recommendations)
                        changed = True
                        stats["rules_processed"] += 1
                        _log_line(
                            log,
                            {
                                "status": "fallback_processed",
                                "file": str(path),
                                "rule_id": rule_id,
                                "rule_uid": rule_uid,
                                "error": str(exc),
                                "vector_text_preview": str(result.get("vector_text", ""))[:120],
                            },
                        )
                    else:
                        stats["rules_failed"] += 1
                        _log_line(
                            log,
                            {
                                "status": "failed",
                                "file": str(path),
                                "rule_id": rule_id,
                                "rule_uid": rule_uid,
                                "error": str(exc),
                            },
                        )

            if changed:
                backup_path = _backup_file(path, timestamp)
                _write_json(path, payload)
                stats["files_changed"] += 1
                _log_line(log, {"status": "file_written", "file": str(path), "backup": str(backup_path)})
            if limit_reached:
                break

    summary_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"summary: {summary_path}")
    print(f"log: {log_path}")


def main():
    parser = argparse.ArgumentParser(description="Rewrite jsonbase recall.vector_text with HyDE-style text via DeepSeek.")
    parser.add_argument("--jsonbase-dir", default=str(DEFAULT_JSONBASE_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--fallback-on-error", action="store_true", default=True)
    parser.add_argument("--limit-rules", type=int, default=0, help="0 means no limit.")
    parser.add_argument("--limit-files", type=int, default=0, help="0 means no limit.")
    parser.add_argument("--overwrite", action="store_true", help="Reprocess rules already reviewed with this prompt version.")
    parser.add_argument("--dry-run", action="store_true", help="Do not call DeepSeek and do not write jsonbase.")
    parser.add_argument(
        "--apply-semantic-recommendations",
        action="store_true",
        help="Also apply semantic_enabled/semantic_role recommendations. Default only records them.",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()

