# -*- coding: utf-8 -*-
"""Compile and prune the approved legal-issue tree for shadow recall."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

from rule_scope import platform_scope_matches


ACTIVE_TRIGGER_LAYERS = {"content", "fact"}
INACTIVE_DISPOSITIONS = {
    "duplicate_source",
    "source_repair_required",
    "workflow_reference",
}


class IssueTreeAssetError(ValueError):
    """Raised when taxonomy, mapping or runtime assets are inconsistent."""


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json_tree(root):
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _values(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _rule_rejection_reason(rule, request, mapping_type=None):
    if rule.get("asset_disposition") in INACTIVE_DISPOSITIONS:
        return "inactive_asset"
    review_roles = rule.get("review_roles")
    if mapping_type and isinstance(review_roles, list) and mapping_type not in review_roles:
        return "review_role_mismatch"
    trigger_layer = ((rule.get("recall") or {}).get("trigger_layer") or "content")
    if trigger_layer not in ACTIVE_TRIGGER_LAYERS:
        return "inactive_trigger_layer"

    context = request.get("context") or {}
    applies_to = rule.get("applies_to") or {}
    industries = set(_values(applies_to.get("industries") or rule.get("industry")))
    industry = str(context.get("industry") or "").strip()
    if industries and not industries.intersection({"通用", "全部", "不限"}) and industry not in industries:
        return "industry_scope_mismatch"
    if not platform_scope_matches(rule, request):
        return "platform_scope_mismatch"

    allowed_types = set(_values(applies_to.get("material_types")))
    material_type = str(context.get("material_type") or "").strip()
    if allowed_types and material_type and material_type not in allowed_types:
        return "material_type_scope_mismatch"
    return ""


def compile_runtime_tree(taxonomy, mapping_asset, rules, source_hashes):
    nodes = taxonomy.get("nodes") or []
    nodes_by_id = {}
    for raw in nodes:
        issue_id = str((raw or {}).get("issue_id") or "").strip()
        if not issue_id:
            raise IssueTreeAssetError("empty_issue_id")
        if issue_id in nodes_by_id:
            raise IssueTreeAssetError(f"duplicate_issue_id:{issue_id}")
        nodes_by_id[issue_id] = dict(raw)

    for issue_id, node in nodes_by_id.items():
        level = node.get("level")
        parent_id = node.get("parent_issue_id")
        if level not in {1, 2, 3}:
            raise IssueTreeAssetError(f"invalid_level:{issue_id}")
        if level == 1:
            if parent_id not in (None, ""):
                raise IssueTreeAssetError(f"invalid_parent:{issue_id}")
            continue
        parent = nodes_by_id.get(parent_id)
        if not parent or parent.get("level") != level - 1:
            raise IssueTreeAssetError(f"invalid_parent:{issue_id}")

    rules_by_uid = {
        str(rule.get("rule_uid") or "").strip(): rule
        for rule in rules or []
        if str(rule.get("rule_uid") or "").strip()
    }
    mappings_by_issue = {}
    compile_exclusions = []
    redirects = mapping_asset.get("uid_redirects") or {}
    for mapping in mapping_asset.get("mappings") or []:
        issue_id = str(mapping.get("issue_id") or "").strip()
        original_uid = str(mapping.get("rule_uid") or "").strip()
        rule_uid = original_uid
        seen_redirects = set()
        while rule_uid in redirects:
            if rule_uid in seen_redirects:
                raise IssueTreeAssetError(f"cyclic_uid_redirect:{original_uid}")
            seen_redirects.add(rule_uid)
            rule_uid = str(redirects[rule_uid] or "").strip()
        mapping_type = str(mapping.get("mapping_type") or "").strip()
        if issue_id not in nodes_by_id:
            raise IssueTreeAssetError(f"missing_issue:{issue_id}")
        if original_uid not in rules_by_uid or rule_uid not in rules_by_uid:
            raise IssueTreeAssetError(f"missing_rule_uid:{rule_uid}")
        if nodes_by_id[issue_id].get("level") != 3:
            compile_exclusions.append({
                "issue_id": issue_id,
                "rule_uid": rule_uid,
                "original_rule_uid": original_uid,
                "mapping_type": mapping_type,
                "reason": "non_leaf_mapping_target",
            })
            continue
        mappings_by_issue.setdefault(issue_id, []).append(
            {
                "rule_uid": rule_uid,
                "original_rule_uid": original_uid,
                "mapping_type": mapping_type,
            }
        )

    children = {}
    for node in nodes_by_id.values():
        children.setdefault(node.get("parent_issue_id"), []).append(node)
    for members in children.values():
        members.sort(key=lambda item: item["issue_id"])

    def build_node(node):
        item = {
            "issue_id": node["issue_id"],
            "name": node.get("name") or "",
            "level": node.get("level"),
        }
        if node.get("definition"):
            item["definition"] = node.get("definition")
        if isinstance(node.get("in_scope"), list):
            item["in_scope"] = node.get("in_scope")
        if isinstance(node.get("out_of_scope"), list):
            item["out_of_scope"] = node.get("out_of_scope")
        if node.get("level") == 3:
            leaf_mappings = sorted(
                mappings_by_issue.get(node["issue_id"], []),
                key=lambda value: (value["mapping_type"], value["rule_uid"]),
            )
            item["available_mapping_roles"] = sorted(
                {value["mapping_type"] for value in leaf_mappings if value["mapping_type"]}
            )
            item["mappings"] = leaf_mappings
        else:
            item["children"] = [build_node(child) for child in children.get(node["issue_id"], [])]
        return item

    branches = [build_node(node) for node in children.get(None, []) + children.get("", [])]
    return {
        "version": "v0.1",
        "source_hashes": dict(sorted((source_hashes or {}).items())),
        "compile_exclusions": sorted(
            compile_exclusions,
            key=lambda item: (item["issue_id"], item["rule_uid"], item["mapping_type"]),
        ),
        "branches": branches,
    }


def write_runtime_tree(payload, output_path):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_runtime_tree(path, expected_hashes=None):
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    actual = payload.get("source_hashes") or {}
    for key, value in (expected_hashes or {}).items():
        if actual.get(key) != value:
            raise IssueTreeAssetError("stale_runtime_asset")
    if payload.get("version") != "v0.1" or not isinstance(payload.get("branches"), list):
        raise IssueTreeAssetError("invalid_runtime_asset")
    return payload


def prune_runtime_tree(runtime_tree, rules_by_uid, request):
    rejected = []

    def prune_node(node):
        if node.get("level") != 3:
            kept_children = []
            for child in node.get("children") or []:
                kept = prune_node(child)
                if kept:
                    kept_children.append(kept)
            if not kept_children:
                return None
            result = copy.deepcopy(node)
            result["children"] = kept_children
            return result

        kept_mappings = []
        for mapping in node.get("mappings") or []:
            rule_uid = mapping.get("rule_uid")
            rule = rules_by_uid.get(rule_uid)
            reason = "missing_rule_uid" if not rule else _rule_rejection_reason(rule, request, mapping.get("mapping_type"))
            if reason:
                rejected.append({"rule_uid": rule_uid, "issue_id": node.get("issue_id"), "reason": reason})
            else:
                kept_mappings.append(copy.deepcopy(mapping))
        if not kept_mappings:
            return None
        result = copy.deepcopy(node)
        result["mappings"] = kept_mappings
        result["available_mapping_roles"] = sorted(
            {item.get("mapping_type") for item in kept_mappings if item.get("mapping_type")}
        )
        return result

    branches = []
    for branch in runtime_tree.get("branches") or []:
        kept = prune_node(branch)
        if kept:
            branches.append(kept)
    result = copy.deepcopy(runtime_tree)
    result["branches"] = branches
    rejected.sort(key=lambda item: (str(item.get("rule_uid")), str(item.get("issue_id"))))
    return result, rejected


def compile_runtime_from_base(base_dir, output_path=None):
    from kg_rule_store import load_rule_library

    base = Path(base_dir)
    approved_dir = base / "reports" / "approved_issue_tree_v03"
    taxonomy_path = approved_dir / "approved_issue_taxonomy_v0.2.json"
    mapping_path = approved_dir / "approved_rule_issue_mapping_v0.2.json"
    output = Path(output_path) if output_path else base / "assets" / "issue_tree_runtime_v0.1.json"
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8-sig"))
    mapping = json.loads(mapping_path.read_text(encoding="utf-8-sig"))
    rules = load_rule_library(base)["data"].get("rules", [])
    runtime = compile_runtime_tree(
        taxonomy,
        mapping,
        rules,
        source_hashes={
            "taxonomy": sha256_file(taxonomy_path),
            "mapping": sha256_file(mapping_path),
            "jsonbase": sha256_json_tree(base / "jsonbase"),
        },
    )
    write_runtime_tree(runtime, output)
    return runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compile approved issue-tree runtime asset.")
    parser.add_argument("--base-dir", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)
    compile_runtime_from_base(args.base_dir, args.output or None)


if __name__ == "__main__":
    main()
