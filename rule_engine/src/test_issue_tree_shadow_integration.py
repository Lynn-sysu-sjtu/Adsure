# -*- coding: utf-8 -*-
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from field_mapper import map_feishu_payload
from kg_rule_store import load_rule_library
from rule_engine import _run_issue_tree_shadow, audit, build_judgment_context_package


PROJECT_BASE = Path(__file__).resolve().parents[1]
PAYLOAD = {
    "material": {"content": "普通护肤文案", "supplemental_background": ""},
    "context": {"industry": "美妆", "platforms": ["抖音"]},
    "request_id": "shadow-integration",
}
BUSINESS_KEYS = (
    "预审_风险等级",
    "审核_审核意见",
    "审核_推荐违规类型",
    "审核_推荐风险等级",
    "matched_rules",
    "rule_judgments",
    "routing",
)


class IssueTreeShadowIntegrationTests(unittest.TestCase):
    def test_real_shadow_helper_attaches_rule_selection_without_replacing_expansion(self):
        request = map_feishu_payload(PAYLOAD)
        context = build_judgment_context_package(request)
        rules = load_rule_library(PROJECT_BASE)['data']['rules']
        leaf = 'SCOPE_ACCESS.AD_REVIEW_ACCESS.PRE_REVIEW_APPROVAL_AND_CONTENT_CONSISTENCY'
        recalled = {
            'enabled': True, 'status': 'ok', 'affected_main_result': False, 'latency_ms': 1,
            'selected_issue_paths': [{'level_3_issue_id': leaf}], 'rejected_paths': [],
        }
        selection = {
            'status': 'ok', 'selected_direct_rule_uids': ['RUID-selected'],
            'selected_fact_check_rule_uids': [],
            'selected_actionable_rule_uids': ['RUID-selected'],
        }
        with patch('rule_engine.recall_issue_tree_shadow', return_value=recalled):
            with patch('rule_engine.select_issue_tree_rules', return_value=selection) as selector:
                result = _run_issue_tree_shadow(PROJECT_BASE, request, context, rules)
        selector.assert_called_once()
        self.assertEqual(selection, result['rule_selection'])
        self.assertIn('eligible_rule_uids_after_gate', result)

    def test_shadow_diagnostics_do_not_change_business_result(self):
        with patch.dict(os.environ, {"ADSURE_ISSUE_TREE_SHADOW_ENABLED": "false"}, clear=False):
            without_shadow = audit(PAYLOAD, base_dir=PROJECT_BASE)

        shadow = {
            "enabled": True,
            "status": "ok",
            "selected_issue_paths": [{"level_3_issue_id": "L1.L2.LEAF"}],
            "direct_rule_uids": ["RUID-tree-only"],
            "affected_main_result": False,
            "latency_ms": 1,
        }
        with patch.dict(os.environ, {"ADSURE_ISSUE_TREE_SHADOW_ENABLED": "true"}, clear=False):
            with patch("rule_engine._run_issue_tree_shadow", return_value=shadow) as runner:
                with_shadow = audit(PAYLOAD, base_dir=PROJECT_BASE)

        runner.assert_called_once()
        for key in BUSINESS_KEYS:
            self.assertEqual(without_shadow["data"][key], with_shadow["data"][key])
        self.assertEqual(shadow, with_shadow["data"]["issue_tree_shadow_recall"])

    def test_disabled_flag_does_not_call_shadow_branch(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("rule_engine._run_issue_tree_shadow") as runner:
                response = audit(PAYLOAD, base_dir=PROJECT_BASE)
        runner.assert_not_called()
        self.assertNotIn("issue_tree_shadow_recall", response["data"])

    def test_shadow_failure_is_diagnostic_only(self):
        failure = {
            "enabled": True,
            "status": "stale_runtime_asset",
            "selected_issue_paths": [],
            "affected_main_result": False,
            "latency_ms": 0,
        }
        with patch.dict(os.environ, {"ADSURE_ISSUE_TREE_SHADOW_ENABLED": "true"}, clear=False):
            with patch("rule_engine._run_issue_tree_shadow", return_value=failure):
                response = audit(PAYLOAD, base_dir=PROJECT_BASE)
        self.assertEqual(0, response["code"])
        self.assertEqual("stale_runtime_asset", response["data"]["issue_tree_shadow_recall"]["status"])


if __name__ == "__main__":
    unittest.main()
