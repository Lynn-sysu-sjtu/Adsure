# -*- coding: utf-8 -*-

import tempfile
import unittest
from pathlib import Path

from export_all_primary_issue_tree_html import (
    ROOT_ORDER,
    assign_numbers,
    export_html,
    load_combined_tree,
    render_document,
    validate_tree,
)


ROOT = Path(__file__).resolve().parents[1]


class AllPrimaryIssueTreeHtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roots = load_combined_tree(ROOT)

    def test_current_assets_form_thirteen_valid_roots(self):
        self.assertEqual([item["issue_id"] for item in self.roots], list(ROOT_ORDER))
        self.assertEqual(len(self.roots), 13)
        result = validate_tree(self.roots)
        self.assertEqual(result["root_count"], 13)
        self.assertEqual(result["invalid_parent_ids"], [])
        self.assertEqual(result["duplicate_ids"], [])
        self.assertGreater(result["level_3_count"], 200)

    def test_numbering_tracks_tree_relationships(self):
        sample = [{
            "issue_id": "A", "name": "一级", "level": 1, "children": [
                {"issue_id": "A.B", "name": "二级", "level": 2, "children": [
                    {"issue_id": "A.B.C", "name": "三级", "level": 3, "children": []},
                ]},
            ],
        }]
        assign_numbers(sample)
        self.assertEqual(sample[0]["number"], "1")
        self.assertEqual(sample[0]["children"][0]["number"], "1.1")
        self.assertEqual(sample[0]["children"][0]["children"][0]["number"], "1.1.1")

    def test_endorsement_leaf_directories_are_expanded_from_reviewed_clusters(self):
        endorsement = next(root for root in self.roots if root["issue_id"] == "ENDORSEMENT_REVIEW")
        children_by_id = {child["issue_id"]: child for child in endorsement["children"]}
        expected = {
            "ENDORSEMENT.RELATION_IDENTIFICATION": 2,
            "ENDORSEMENT.CONSENT_FOR_NAME_IMAGE": 6,
            "ENDORSEMENT.ACTUAL_USE_DUTY": 5,
            "ENDORSEMENT.JOINT_LIABILITY": 5,
        }
        for issue_id, expected_rule_count in expected.items():
            directory = children_by_id[issue_id]
            self.assertGreater(len(directory["children"]), 0, issue_id)
            self.assertEqual(directory["level_3_count"], len(directory["children"]))
            self.assertEqual(directory["rule_count"], expected_rule_count)

    def test_render_contains_review_controls_and_definitions(self):
        document = render_document(self.roots)
        self.assertIn('<meta charset="utf-8">', document.lower())
        self.assertIn("全部问题树", document)
        self.assertIn("仅看中低置信度", document)
        self.assertIn("全部展开", document)
        self.assertIn("问题定义", document)
        self.assertIn("data-parent-id", document)
        self.assertIn("showAncestors", document)
        self.assertIn("draft，仅供目录关系审核", document)

    def test_export_writes_utf8_html(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tree.html"
            result = export_html(ROOT, target)
            payload = target.read_bytes()
        self.assertTrue(payload.startswith(b"<!doctype html>"))
        self.assertIn("广告合规".encode("utf-8"), payload)
        self.assertEqual(result["root_count"], 13)


if __name__ == "__main__":
    unittest.main()
