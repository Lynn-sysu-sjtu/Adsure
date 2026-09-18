# -*- coding: utf-8 -*-
import unittest

from issue_tree_shadow_eval import evaluate_shadow_cases, run_shadow_cases


class IssueTreeShadowEvalTests(unittest.TestCase):
    def test_recall_counts_repeated_expected_uid_per_case(self):
        result = evaluate_shadow_cases([
            {"expected_rule_uids": ["R-1"], "tree_rule_uids": ["R-1"], "tree_status": "ok"},
            {"expected_rule_uids": ["R-1"], "tree_rule_uids": [], "tree_status": "empty"},
        ])
        self.assertEqual(2, result["expected_rule_count"])
        self.assertEqual(1, result["matched_expected_rule_count"])
        self.assertEqual(0.5, result["rule_uid_recall"])

    def test_runs_input_payload_cases_and_extracts_shadow_diagnostics(self):
        calls = []

        def fake_audit(payload, base_dir=None, diagnostics=None):
            calls.append(payload)
            diagnostics.update({"candidate_rule_uids": ["R-1"]})
            return {"code": 0, "data": {
                "matched_rules": [{"rule_uid": "R-1", "recall_channel": "keyword"}],
                "issue_tree_shadow_recall": {
                    "status": "ok",
                    "selected_issue_paths": [{"level_3_issue_id": "I-1"}],
                    "eligible_rule_uids_after_gate": ["R-1", "R-2"],
                    "rejected_paths": [{"reason": "invalid_issue_path"}],
                    "rule_selection": {
                        "status": "ok", "semantic_status": "ok",
                        "selected_direct_rule_uids": ["R-2"],
                        "selected_fact_check_rule_uids": ["R-3"],
                        "selected_actionable_rule_uids": ["R-2", "R-3"],
                        "dropped_rules": [{"rule_uid": "R-4", "drop_reason": "per_path_limit_exceeded"}],
                        "path_rankings": [],
                    },
                    "latency_ms": 12,
                },
            }}

        result = run_shadow_cases(
            [{"case_id": "C-1", "input_payload": {"material": {"content": "文案"}},
              "expected": {"must_recall_rule_uids": ["R-1"]}}],
            fake_audit,
        )
        self.assertEqual(1, len(calls))
        self.assertEqual(["R-1", "R-2"], result[0]["tree_rule_uids"])
        self.assertEqual(["R-1"], result[0]["keyword_rule_uids"])
        self.assertEqual("ok", result[0]["tree_status"])
        self.assertEqual(["R-2"], result[0]["tree_selected_direct_rule_uids"])
        self.assertEqual(["R-3"], result[0]["tree_selected_fact_check_rule_uids"])
        self.assertEqual(["R-2", "R-3"], result[0]["tree_selected_actionable_rule_uids"])
        self.assertEqual([{"reason": "invalid_issue_path"}], result[0]["tree_rejected_paths"])

    def test_computes_recall_channel_overlap_and_latency(self):
        cases = [
            {
                "expected_issue_ids": ["I-1", "I-2"],
                "expected_rule_uids": ["R-1", "R-2"],
                "keyword_rule_uids": ["R-1"],
                "semantic_rule_uids": ["R-3"],
                "tree_issue_ids": ["I-1"],
                "tree_rule_uids": ["R-1", "R-4"],
                "tree_status": "ok",
                "invalid_path_count": 0,
                "latency_ms": 100,
            },
            {
                "expected_issue_ids": ["I-3"],
                "expected_rule_uids": ["R-5"],
                "keyword_rule_uids": [],
                "semantic_rule_uids": ["R-5"],
                "tree_issue_ids": ["I-3"],
                "tree_rule_uids": ["R-5"],
                "tree_status": "empty",
                "invalid_path_count": 1,
                "latency_ms": 300,
            },
        ]

        result = evaluate_shadow_cases(cases)

        self.assertEqual(2, result["case_count"])
        self.assertEqual(2, result["matched_expected_issue_count"])
        self.assertEqual(3, result["expected_issue_count"])
        self.assertEqual(2, result["matched_expected_rule_count"])
        self.assertEqual(3, result["expected_rule_count"])
        self.assertEqual(["R-4"], result["tree_only_rule_uids"])
        self.assertEqual(["R-2"], result["missed_by_tree_rule_uids"])
        self.assertEqual(1, result["invalid_path_count"])
        self.assertEqual({"empty": 1, "ok": 1}, result["status_counts"])
        self.assertEqual(300, result["p95_latency_ms"])

    def test_computes_selected_actionable_metrics_and_limit_violations(self):
        result = evaluate_shadow_cases([
            {
                "expected_rule_uids": ["R-1", "R-2"],
                "candidate_rule_uids": ["R-1"],
                "tree_rule_uids": ["R-1", "R-2", "R-X"],
                "tree_selected_direct_rule_uids": ["R-2"],
                "tree_selected_fact_check_rule_uids": ["R-1"],
                "tree_selected_actionable_rule_uids": ["R-2", "R-1"],
                "tree_selection_path_rankings": [
                    {"issue_id": "I-1", "per_path_selected_rule_uids": ["R-2", "R-1"]}
                ],
                "tree_non_actionable_rule_uids": ["R-X"],
                "tree_status": "ok", "tree_semantic_status": "provider_error",
                "latency_ms": 10,
            }
        ])
        self.assertEqual(2, result["selected_actionable_expected_rule_hits"])
        self.assertEqual(2, result["selected_actionable_expected_rule_count"])
        self.assertEqual(1, result["selected_actionable_complete_case_hits"])
        self.assertEqual(["R-2"], result["selected_tree_only_rule_uids"])
        self.assertEqual(0, result["role_promotion_violation_count"])
        self.assertEqual(0, result["per_case_limit_violation_count"])
        self.assertEqual(0, result["per_path_limit_violation_count"])
        self.assertEqual({"provider_error": 1}, result["semantic_status_counts"])

    def test_dual_role_uid_is_not_promoted_when_selected_as_fact_check(self):
        result = evaluate_shadow_cases([{
            "tree_selected_direct_rule_uids": [],
            "tree_selected_fact_check_rule_uids": ["R-DUAL"],
            "tree_selected_actionable_rule_uids": ["R-DUAL"],
            "tree_non_actionable_rule_uids": ["R-DUAL", "R-SUPPORT"],
            "tree_selection_path_rankings": [{
                "issue_id": "I-FACT",
                "ranked_rules": [{"rule_uid": "R-DUAL", "mapping_role": "fact_check"}],
                "per_path_selected_rule_uids": ["R-DUAL"],
            }],
        }])
        self.assertEqual(0, result["role_promotion_violation_count"])

    def test_non_actionable_uid_without_selected_actionable_provenance_is_violation(self):
        result = evaluate_shadow_cases([{
            "tree_selected_actionable_rule_uids": ["R-SUPPORT"],
            "tree_non_actionable_rule_uids": ["R-SUPPORT"],
            "tree_selection_path_rankings": [],
        }])
        self.assertEqual(1, result["role_promotion_violation_count"])


if __name__ == "__main__":
    unittest.main()
