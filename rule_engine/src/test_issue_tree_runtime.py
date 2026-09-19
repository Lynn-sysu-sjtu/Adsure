# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from issue_tree_runtime import (
    IssueTreeAssetError,
    compile_runtime_tree,
    load_runtime_tree,
    prune_runtime_tree,
    write_runtime_tree,
)


def _taxonomy():
    return {
        "nodes": [
            {"issue_id": "L1", "parent_issue_id": None, "level": 1, "name": "一级"},
            {"issue_id": "L1.L2", "parent_issue_id": "L1", "level": 2, "name": "二级"},
            {
                "issue_id": "L1.L2.LEAF",
                "parent_issue_id": "L1.L2",
                "level": 3,
                "name": "直接问题",
                "definition": "正文直接出现问题",
            },
            {
                "issue_id": "L1.L2.PLATFORM",
                "parent_issue_id": "L1.L2",
                "level": 3,
                "name": "平台问题",
                "definition": "仅适用于小红书",
            },
        ]
    }


def _mapping():
    return {
        "mappings": [
            {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-1", "mapping_type": "direct"},
            {"issue_id": "L1.L2.PLATFORM", "rule_uid": "RUID-2", "mapping_type": "fact_check"},
        ],
        "excluded_mappings": [],
    }


def _rules():
    return [
        {
            "rule_uid": "RUID-1",
            "recall": {"trigger_layer": "content"},
            "applies_to": {"industries": ["通用"]},
        },
        {
            "rule_uid": "RUID-2",
            "recall": {"trigger_layer": "fact"},
            "applies_to": {"industries": ["美妆"], "platforms": ["小红书"]},
        },
    ]


class IssueTreeRuntimeTests(unittest.TestCase):
    def test_compiles_stable_nested_tree_and_mapping_roles(self):
        runtime = compile_runtime_tree(
            _taxonomy(), _mapping(), _rules(), source_hashes={"taxonomy": "t"}
        )

        self.assertEqual("v0.1", runtime["version"])
        leaf = runtime["branches"][0]["children"][0]["children"][0]
        self.assertEqual("L1.L2.LEAF", leaf["issue_id"])
        self.assertEqual(["direct"], leaf["available_mapping_roles"])
        self.assertEqual("t", runtime["source_hashes"]["taxonomy"])

    def test_rejects_duplicate_nodes_and_missing_mapping_targets(self):
        duplicate = _taxonomy()
        duplicate["nodes"].append(dict(duplicate["nodes"][0]))
        with self.assertRaisesRegex(IssueTreeAssetError, "duplicate_issue_id"):
            compile_runtime_tree(duplicate, _mapping(), _rules(), {})

        missing_issue = _mapping()
        missing_issue["mappings"].append(
            {"issue_id": "UNKNOWN", "rule_uid": "RUID-1", "mapping_type": "direct"}
        )
        with self.assertRaisesRegex(IssueTreeAssetError, "missing_issue"):
            compile_runtime_tree(_taxonomy(), missing_issue, _rules(), {})

    def test_rejects_bad_parent_and_missing_rule_uid(self):
        taxonomy = _taxonomy()
        taxonomy["nodes"][1]["parent_issue_id"] = "UNKNOWN"
        with self.assertRaisesRegex(IssueTreeAssetError, "invalid_parent"):
            compile_runtime_tree(taxonomy, _mapping(), _rules(), {})

        with self.assertRaisesRegex(IssueTreeAssetError, "missing_rule_uid"):
            compile_runtime_tree(_taxonomy(), _mapping(), _rules()[:1], {})

    def test_records_non_leaf_mappings_as_runtime_exclusions(self):
        mapping = _mapping()
        mapping["mappings"].append(
            {"issue_id": "L1.L2", "rule_uid": "RUID-1", "mapping_type": "direct"}
        )

        runtime = compile_runtime_tree(_taxonomy(), mapping, _rules(), {})

        self.assertEqual(
            [{
                "issue_id": "L1.L2",
                "rule_uid": "RUID-1",
                "original_rule_uid": "RUID-1",
                "mapping_type": "direct",
                "reason": "non_leaf_mapping_target",
            }],
            runtime["compile_exclusions"],
        )

    def test_redirected_duplicate_mapping_keeps_canonical_leaf_available(self):
        mapping = {
            "mappings": [
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-old", "mapping_type": "direct"}
            ],
            "uid_redirects": {"RUID-old": "RUID-1"},
        }
        rules = _rules() + [{
            "rule_uid": "RUID-old",
            "asset_disposition": "duplicate_source",
            "recall": {"trigger_layer": "content"},
        }]
        runtime = compile_runtime_tree(_taxonomy(), mapping, rules, {})
        pruned, _ = prune_runtime_tree(
            runtime, {rule["rule_uid"]: rule for rule in rules},
            {"context": {"industry": "美妆", "platforms": ["抖音"]}},
        )

        leaf = pruned["branches"][0]["children"][0]["children"][0]
        self.assertEqual("RUID-1", leaf["mappings"][0]["rule_uid"])
        self.assertEqual("RUID-old", leaf["mappings"][0]["original_rule_uid"])

    def test_load_rejects_stale_source_hash(self):
        runtime = compile_runtime_tree(_taxonomy(), _mapping(), _rules(), {"taxonomy": "old"})
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime.json"
            write_runtime_tree(runtime, path)
            with self.assertRaisesRegex(IssueTreeAssetError, "stale_runtime_asset"):
                load_runtime_tree(path, expected_hashes={"taxonomy": "new"})

    def test_prunes_platform_leaf_without_selected_matching_platform(self):
        runtime = compile_runtime_tree(_taxonomy(), _mapping(), _rules(), {})
        pruned, rejected = prune_runtime_tree(
            runtime,
            {rule["rule_uid"]: rule for rule in _rules()},
            {"context": {"industry": "美妆", "platforms": ["抖音"]}},
        )

        leaves = pruned["branches"][0]["children"][0]["children"]
        self.assertEqual(["L1.L2.LEAF"], [item["issue_id"] for item in leaves])
        self.assertEqual("platform_scope_mismatch", rejected[0]["reason"])

    def test_material_type_alias_survives_runtime_gate(self):
        rules = _rules()
        rules[0]["applies_to"]["material_types"] = ["短视频脚本中的文字内容"]
        runtime = compile_runtime_tree(_taxonomy(), _mapping(), rules, {})
        pruned, rejected = prune_runtime_tree(
            runtime,
            {rule["rule_uid"]: rule for rule in rules},
            {
                "context": {
                    "industry": "美妆",
                    "platforms": ["抖音"],
                    "material_type": "短视频脚本",
                }
            },
        )
        leaves = pruned["branches"][0]["children"][0]["children"]
        self.assertIn("L1.L2.LEAF", [item["issue_id"] for item in leaves])
        self.assertNotIn(
            "material_type_scope_mismatch",
            [item["reason"] for item in rejected],
        )


    def test_prunes_mapping_when_explicit_review_role_disagrees(self):
        rules = _rules()
        rules[0]["review_roles"] = ["supporting_basis"]
        runtime = compile_runtime_tree(_taxonomy(), _mapping(), rules, {})
        pruned, rejected = prune_runtime_tree(
            runtime, {rule["rule_uid"]: rule for rule in rules},
            {"context": {"industry": "美妆", "platforms": ["抖音"]}},
        )
        self.assertEqual([], pruned["branches"])
        self.assertIn("review_role_mismatch", [item["reason"] for item in rejected])


if __name__ == "__main__":
    unittest.main()
