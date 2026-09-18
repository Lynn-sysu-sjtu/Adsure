# -*- coding: utf-8 -*-
import json
import os
import unittest
from unittest.mock import patch

from issue_tree_shadow_recall import (
    build_issue_tree_messages,
    recall_issue_tree_shadow,
    validate_selected_paths,
)


def _tree():
    return {
        "version": "v0.1",
        "branches": [{
            "issue_id": "L1", "name": "一级", "level": 1,
            "children": [{
                "issue_id": "L1.L2", "name": "二级", "level": 2,
                "children": [{
                    "issue_id": "L1.L2.LEAF", "name": "功效超范围", "level": 3,
                    "definition": "具体功效需要核验", "available_mapping_roles": ["fact_check"],
                    "mappings": [{"rule_uid": "RUID-secret", "mapping_type": "fact_check"}],
                }],
            }],
        }],
    }


def _payload(**changes):
    path = {
        "level_1_issue_id": "L1",
        "level_2_issue_id": "L1.L2",
        "level_3_issue_id": "L1.L2.LEAF",
        "trigger_source": "content",
        "content_evidence": "7天彻底祛斑",
        "context_evidence": "",
        "reason": "存在具体功效宣称",
        "suggested_outcome": "fact_check",
        "confidence": 0.9,
    }
    path.update(changes)
    return {"selected_paths": [path]}


class _Client:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def create_chat_completion(self, messages, **kwargs):
        if self.error:
            raise self.error
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


class IssueTreeShadowRecallTests(unittest.TestCase):
    def test_prompt_contains_context_and_tree_but_not_rule_uids(self):
        messages = build_issue_tree_messages(
            {
                "material_text": "7天彻底祛斑",
                "supplemental_background": "普通化妆品",
                "industry": "美妆",
                "platforms": ["抖音"],
            },
            _tree(),
        )
        prompt = messages[1]["content"]
        self.assertIn("7天彻底祛斑", prompt)
        self.assertIn("普通化妆品", prompt)
        self.assertIn("L1.L2.LEAF", prompt)
        self.assertIn("每个一级问题最多3个二级问题", prompt)
        self.assertNotIn("RUID-secret", prompt)
        self.assertNotIn("mappings", prompt)

    def test_prompt_does_not_leak_compile_exclusion_uids(self):
        tree = _tree()
        tree["compile_exclusions"] = [{
            "issue_id": "L1.L2",
            "rule_uid": "RUID-excluded-secret",
            "reason": "non_leaf_mapping_target",
        }]
        prompt = build_issue_tree_messages({"material_text": "普通文案"}, tree)[1]["content"]
        self.assertNotIn("RUID-excluded-secret", prompt)

    def test_accepts_valid_path_with_contiguous_content_evidence(self):
        valid, rejected = validate_selected_paths(
            _payload(), _tree(), "新品：7天彻底祛斑！", "普通化妆品"
        )
        self.assertEqual(1, len(valid))
        self.assertEqual([], rejected)

    def test_rejects_unknown_parent_duplicate_and_wrong_evidence_source(self):
        invalid = _payload(level_2_issue_id="UNKNOWN")
        valid, rejected = validate_selected_paths(invalid, _tree(), "7天彻底祛斑", "普通化妆品")
        self.assertEqual([], valid)
        self.assertEqual("invalid_issue_path", rejected[0]["reason"])

        duplicate = _payload()
        duplicate["selected_paths"].append(dict(duplicate["selected_paths"][0]))
        valid, rejected = validate_selected_paths(duplicate, _tree(), "7天彻底祛斑", "")
        self.assertEqual(1, len(valid))
        self.assertIn("duplicate_leaf", [item["reason"] for item in rejected])

        wrong_source = _payload(content_evidence="普通化妆品")
        valid, rejected = validate_selected_paths(wrong_source, _tree(), "7天彻底祛斑", "普通化妆品")
        self.assertEqual([], valid)
        self.assertEqual("content_evidence_not_found", rejected[0]["reason"])

    def test_rejects_background_only_direct_and_invalid_confidence(self):
        background_direct = _payload(
            trigger_source="context",
            content_evidence="",
            context_evidence="普通化妆品",
            suggested_outcome="direct",
        )
        valid, rejected = validate_selected_paths(
            background_direct, _tree(), "普通文案", "普通化妆品"
        )
        self.assertEqual([], valid)
        self.assertEqual("background_cannot_confirm_direct", rejected[0]["reason"])

        valid, rejected = validate_selected_paths(
            _payload(confidence=1.2), _tree(), "7天彻底祛斑", ""
        )
        self.assertEqual([], valid)
        self.assertEqual("invalid_confidence", rejected[0]["reason"])

    def test_provider_failure_is_a_non_blocking_stable_result(self):
        result = recall_issue_tree_shadow(
            {"material_text": "普通文案", "supplemental_background": ""},
            _tree(),
            client=_Client(error=RuntimeError("boom")),
        )
        self.assertEqual("provider_error", result["status"])
        self.assertFalse(result["affected_main_result"])
        self.assertEqual([], result["selected_issue_paths"])

    def test_mock_backend_returns_empty_without_provider_call(self):
        with patch.dict(os.environ, {"ADSURE_ISSUE_TREE_BACKEND": "mock"}):
            result = recall_issue_tree_shadow(
                {"material_text": "普通文案", "supplemental_background": ""},
                _tree(),
                client=_Client(error=AssertionError("provider must not be called")),
            )
        self.assertEqual("empty", result["status"])
        self.assertFalse(result["affected_main_result"])

    def test_successful_client_response_returns_validated_paths(self):
        result = recall_issue_tree_shadow(
            {"material_text": "7天彻底祛斑", "supplemental_background": "普通化妆品"},
            _tree(), client=_Client(_payload()),
        )
        self.assertEqual("ok", result["status"])
        self.assertEqual("L1.L2.LEAF", result["selected_issue_paths"][0]["level_3_issue_id"])


if __name__ == "__main__":
    unittest.main()
