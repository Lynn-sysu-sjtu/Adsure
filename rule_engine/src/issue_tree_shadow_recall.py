# -*- coding: utf-8 -*-
"""Single-call DeepSeek issue-path selection for non-blocking shadow recall."""

import copy
import json
import os
import re
import time

from issue_tree_targeted_path_policy import targeted_issue_paths

VALID_TRIGGER_SOURCES = {"content", "context", "mixed"}
VALID_OUTCOMES = {"direct", "fact_check", "proactive_check", "uncertain"}


def _prompt_tree(runtime_tree):
    tree = copy.deepcopy(runtime_tree)

    def clean(node):
        node.pop("mappings", None)
        for child in node.get("children") or []:
            clean(child)

    for branch in tree.get("branches") or []:
        clean(branch)
    tree.pop("source_hashes", None)
    tree.pop("compile_exclusions", None)
    return tree


def build_issue_tree_messages(context_package, pruned_tree):
    system = (
        "你是广告合规法律问题目录召回器。你只选择输入目录中真实存在的完整问题路径，"
        "不得生成法条、规则UID、风险等级、处罚结论或最终分流。没有可靠路径时返回空数组。只输出JSON。"
    )
    payload = {
        "task": "从一级、二级、三级问题树中选择与当前物料有关的完整路径；不判断最终违法。",
        "limits": {
            "一级问题": "最多3个",
            "二级问题": "每个一级问题最多3个二级问题",
            "三级问题": "每个二级问题最多3个三级问题",
        },
        "evidence_policy": {
            "content_evidence": "必须逐字复制广告正文中的单个连续片段",
            "context_evidence": "必须逐字复制运营补充背景中的单个连续片段，只能帮助理解或触发事实核验",
            "structured_context": "行业、平台、品类和物料类型只用于范围理解，不能单独证明违法",
            "background_direct_rule": "只有背景证据时不得建议direct",
        },
        "material": {
            "content": context_package.get("material_text") or "",
            "supplemental_background": context_package.get("supplemental_background") or "",
            "industry": context_package.get("industry") or "",
            "material_type": context_package.get("material_type") or "",
            "platforms": context_package.get("platforms") or [],
            "product_category": context_package.get("product_category") or "",
            "core_claims": context_package.get("core_claims") or [],
            "scenario": context_package.get("scenario") or "",
        },
        "issue_tree": _prompt_tree(pruned_tree),
        "output_contract": {
            "selected_paths": [{
                "level_1_issue_id": "目录中的一级ID",
                "level_2_issue_id": "目录中的二级ID",
                "level_3_issue_id": "目录中的三级ID",
                "trigger_source": "content | context | mixed",
                "content_evidence": "正文连续原文或空字符串",
                "context_evidence": "背景连续原文或空字符串",
                "reason": "选择该问题的简短原因",
                "suggested_outcome": "direct | fact_check | proactive_check | uncertain",
                "confidence": "0到1之间的数字",
            }]
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def parse_issue_tree_response(response):
    if isinstance(response, dict):
        return response
    text = str(response or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("response_not_object")
    return parsed


def _tree_path_index(pruned_tree):
    paths = set()
    for level_1 in pruned_tree.get("branches") or []:
        for level_2 in level_1.get("children") or []:
            for level_3 in level_2.get("children") or []:
                paths.add((level_1.get("issue_id"), level_2.get("issue_id"), level_3.get("issue_id")))
    return paths


def _path_priority(item, original_index):
    return (
        not bool(item.get("targeted_path_priority_applied")),
        not bool(str(item.get("content_evidence") or "")),
        item.get("suggested_outcome") != "direct",
        {"content": 0, "mixed": 1, "context": 2}.get(item.get("trigger_source"), 3),
        -float(item.get("confidence") or 0),
        original_index,
    )


def _order_paths_with_family_diversity(paths):
    indexed = list(enumerate(paths))
    indexed.sort(key=lambda pair: _path_priority(pair[1], pair[0]))
    family_order = []
    by_family = {}
    for original_index, item in indexed:
        family = str(item.get("level_1_issue_id") or "")
        if family not in by_family:
            family_order.append(family)
            by_family[family] = []
        by_family[family].append((original_index, item))
    ordered = []
    round_index = 0
    while True:
        added = False
        for family in family_order:
            queue = by_family[family]
            if round_index < len(queue):
                ordered.append(queue[round_index][1])
                added = True
        if not added:
            break
        round_index += 1
    return ordered


def _apply_path_limits(paths):
    accepted = []
    displaced = []
    l1_ids = set()
    l2_by_l1 = {}
    l3_by_l2 = {}
    for ranked_index, item in enumerate(paths, start=1):
        path = (
            item.get("level_1_issue_id"),
            item.get("level_2_issue_id"),
            item.get("level_3_issue_id"),
        )
        candidate_l1 = l1_ids | {path[0]}
        candidate_l2 = l2_by_l1.get(path[0], set()) | {path[1]}
        candidate_l3 = l3_by_l2.get(path[1], set()) | {path[2]}
        if len(candidate_l1) > 3 or len(candidate_l2) > 3 or len(candidate_l3) > 3:
            displaced.append({
                "level_3_issue_id": path[2],
                "reason": "path_limit_exceeded",
                "ranked_position": ranked_index,
                "retained_issue_ids": [
                    retained.get("level_3_issue_id") for retained in accepted
                ],
            })
            continue
        l1_ids = candidate_l1
        l2_by_l1[path[0]] = candidate_l2
        l3_by_l2[path[1]] = candidate_l3
        accepted.append(item)
    return accepted, displaced


def validate_selected_paths(
    payload, pruned_tree, content, supplemental_background, diagnostics=None,
    preserved_paths=None, preservation_tree=None,
):
    items = payload.get("selected_paths") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return [], [{"reason": "selected_paths_not_array"}]
    valid_paths = _tree_path_index(pruned_tree)
    preservation_paths = _tree_path_index(preservation_tree or pruned_tree)
    accepted = []
    rejected = []
    seen_leaves = set()
    l1_ids = set()
    l2_by_l1 = {}
    l3_by_l2 = {}

    for raw in items:
        if not isinstance(raw, dict):
            rejected.append({"reason": "path_not_object"})
            continue
        item = dict(raw)
        path = (
            item.get("level_1_issue_id"),
            item.get("level_2_issue_id"),
            item.get("level_3_issue_id"),
        )
        leaf = path[2]
        if path not in valid_paths:
            rejected.append({"level_3_issue_id": leaf, "reason": "invalid_issue_path"})
            continue
        if leaf in seen_leaves:
            rejected.append({"level_3_issue_id": leaf, "reason": "duplicate_leaf"})
            continue
        candidate_l1 = l1_ids | {path[0]}
        candidate_l2 = l2_by_l1.get(path[0], set()) | {path[1]}
        candidate_l3 = l3_by_l2.get(path[1], set()) | {path[2]}
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            rejected.append({"level_3_issue_id": leaf, "reason": "invalid_confidence"})
            continue
        source = item.get("trigger_source")
        outcome = item.get("suggested_outcome")
        if source not in VALID_TRIGGER_SOURCES or outcome not in VALID_OUTCOMES:
            rejected.append({"level_3_issue_id": leaf, "reason": "invalid_enum"})
            continue
        content_evidence = str(item.get("content_evidence") or "")
        context_evidence = str(item.get("context_evidence") or "")
        if content_evidence and content_evidence not in str(content or ""):
            rejected.append({"level_3_issue_id": leaf, "reason": "content_evidence_not_found"})
            continue
        if context_evidence and context_evidence not in str(supplemental_background or ""):
            rejected.append({"level_3_issue_id": leaf, "reason": "context_evidence_not_found"})
            continue
        if source == "content" and not content_evidence:
            rejected.append({"level_3_issue_id": leaf, "reason": "missing_content_evidence"})
            continue
        if source == "context" and not context_evidence:
            rejected.append({"level_3_issue_id": leaf, "reason": "missing_context_evidence"})
            continue
        if not content_evidence and outcome == "direct":
            rejected.append({"level_3_issue_id": leaf, "reason": "background_cannot_confirm_direct"})
            continue

        seen_leaves.add(leaf)
        l1_ids = candidate_l1
        l2_by_l1[path[0]] = candidate_l2
        l3_by_l2[path[1]] = candidate_l3
        accepted.append(item)
    applied_preservations = []
    for item in preserved_paths or []:
        path = (
            item.get("level_1_issue_id"),
            item.get("level_2_issue_id"),
            item.get("level_3_issue_id"),
        )
        leaf = path[2]
        if path not in preservation_paths:
            continue
        if leaf in seen_leaves:
            existing = next(
                candidate
                for candidate in accepted
                if candidate.get("level_3_issue_id") == leaf
            )
            existing["targeted_path_policy_id"] = item.get("targeted_path_policy_id")
            existing["targeted_path_priority_applied"] = True
            existing["suggested_outcome"] = item.get("suggested_outcome")
            existing["confidence"] = max(
                float(existing.get("confidence") or 0),
                float(item.get("confidence") or 0),
            )
            if not existing.get("content_evidence"):
                existing["content_evidence"] = item.get("content_evidence") or ""
            if not existing.get("context_evidence"):
                existing["context_evidence"] = item.get("context_evidence") or ""
            applied_preservations.append(dict(existing))
            continue
        seen_leaves.add(leaf)
        accepted.append(dict(item))
        applied_preservations.append(dict(item))
    ordered = _order_paths_with_family_diversity(accepted)
    selected, limit_displacements = _apply_path_limits(ordered)
    if diagnostics is not None:
        diagnostics.update({
            "pre_limit_valid_paths": ordered,
            "post_limit_selected_paths": selected,
            "limit_displacements": limit_displacements,
            "targeted_path_preservations": applied_preservations,
        })
    return selected, rejected + limit_displacements


def _message_content(response):
    return (((response or {}).get("choices") or [{}])[0].get("message") or {}).get("content", "")


def recall_issue_tree_shadow(
    context_package, pruned_tree, client=None, timeout=5, preservation_tree=None,
):
    started = time.monotonic()
    base = {
        "enabled": True,
        "status": "provider_error",
        "selected_issue_paths": [],
        "rejected_paths": [],
        "affected_main_result": False,
        "latency_ms": 0,
    }
    try:
        if not pruned_tree.get("branches"):
            base["status"] = "empty"
            return base
        if (os.getenv("ADSURE_ISSUE_TREE_BACKEND") or "").lower() == "mock":
            base["status"] = "empty"
            return base
        if client is None:
            from deepseek_client import DeepSeekClient
            client = DeepSeekClient(timeout=max(1, int(timeout)))
        model = os.getenv("ADSURE_ISSUE_TREE_MODEL") or "deepseek-chat"
        response = client.create_chat_completion(
            build_issue_tree_messages(context_package, pruned_tree),
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        parsed = parse_issue_tree_response(_message_content(response))
        path_diagnostics = {}
        policy_tree = preservation_tree or pruned_tree
        accepted, rejected = validate_selected_paths(
            parsed,
            pruned_tree,
            context_package.get("material_text") or "",
            context_package.get("supplemental_background") or "",
            diagnostics=path_diagnostics,
            preserved_paths=targeted_issue_paths(context_package, policy_tree),
            preservation_tree=policy_tree,
        )
        base.update(path_diagnostics)
        base["selected_issue_paths"] = accepted
        base["rejected_paths"] = rejected
        base["status"] = "ok" if accepted else "empty"
        if rejected and not accepted:
            base["status"] = "invalid_response"
            base["reason_code"] = rejected[0].get("reason")
    except TimeoutError:
        base["status"] = "timeout"
        base["reason_code"] = "provider_timeout"
    except (json.JSONDecodeError, ValueError) as exc:
        base["status"] = "invalid_response"
        base["reason_code"] = str(exc)
    except Exception:
        base["status"] = "provider_error"
        base["reason_code"] = "provider_call_failed"
    finally:
        base["latency_ms"] = max(0, int((time.monotonic() - started) * 1000))
    return base
