# -*- coding: utf-8 -*-
import unittest

from issue_tree_mapping import expand_issue_paths


class IssueTreeMappingTests(unittest.TestCase):
    def setUp(self):
        self.mapping = {
            "mappings": [
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-old", "mapping_type": "direct"},
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-fact", "mapping_type": "fact_check"},
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-pro", "mapping_type": "proactive_check"},
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-support", "mapping_type": "supporting_basis"},
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-exception", "mapping_type": "exception"},
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-xhs", "mapping_type": "direct"},
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-inactive", "mapping_type": "direct"},
            ],
            "excluded_mappings": [
                {"issue_id": "L1.L2.LEAF", "rule_uid": "RUID-excluded", "mapping_type": "direct"}
            ],
        }
        self.rules = {
            "RUID-canonical": self._rule("RUID-canonical"),
            "RUID-fact": self._rule("RUID-fact"),
            "RUID-pro": self._rule("RUID-pro"),
            "RUID-support": self._rule("RUID-support"),
            "RUID-exception": self._rule("RUID-exception"),
            "RUID-xhs": self._rule("RUID-xhs", platforms=["小红书"]),
            "RUID-inactive": self._rule("RUID-inactive", disposition="source_repair_required"),
            "RUID-excluded": self._rule("RUID-excluded"),
        }
        self.request = {"context": {"industry": "美妆", "platforms": ["抖音"]}}

    @staticmethod
    def _rule(uid, platforms=None, disposition=""):
        return {
            "rule_uid": uid,
            "asset_disposition": disposition,
            "recall": {"trigger_layer": "content"},
            "applies_to": {"industries": ["美妆"], "platforms": platforms or []},
        }

    def test_expands_roles_without_promoting_non_direct_rules(self):
        result = expand_issue_paths(
            ["L1.L2.LEAF"],
            self.mapping,
            self.rules,
            self.request,
            uid_redirects={"RUID-old": "RUID-canonical"},
        )

        self.assertEqual(["RUID-canonical"], result["direct_rule_uids"])
        self.assertEqual(["RUID-fact"], result["fact_check_rule_uids"])
        self.assertEqual(["RUID-pro"], result["proactive_check_rule_uids"])
        self.assertEqual(["RUID-support"], result["supporting_rule_uids"])
        self.assertEqual(["RUID-exception"], result["exception_rule_uids"])

    def test_preserves_redirect_trace_and_rejection_reasons(self):
        result = expand_issue_paths(
            ["L1.L2.LEAF"],
            self.mapping,
            self.rules,
            self.request,
            uid_redirects={"RUID-old": "RUID-canonical"},
        )

        redirect_trace = next(item for item in result["trace"] if item["canonical_rule_uid"] == "RUID-canonical")
        self.assertEqual(["RUID-old"], redirect_trace["original_rule_uids"])
        rejected = {item["rule_uid"]: item["reason"] for item in result["rejected_rule_uids"]}
        self.assertEqual("platform_scope_mismatch", rejected["RUID-xhs"])
        self.assertEqual("inactive_asset", rejected["RUID-inactive"])

    def test_excluded_and_unselected_mappings_never_expand(self):
        result = expand_issue_paths(
            ["OTHER.LEAF"], self.mapping, self.rules, self.request, uid_redirects={}
        )
        self.assertEqual([], result["mapped_rule_uids_before_gate"])
        self.assertNotIn("RUID-excluded", str(result))

    def test_explicit_review_role_cannot_be_promoted_by_mapping(self):
        self.rules["RUID-canonical"]["review_roles"] = ["supporting_basis"]
        result = expand_issue_paths(
            ["L1.L2.LEAF"], self.mapping, self.rules, self.request,
            uid_redirects={"RUID-old": "RUID-canonical"},
        )
        self.assertNotIn("RUID-canonical", result["direct_rule_uids"])
        self.assertIn("review_role_mismatch", [item["reason"] for item in result["rejected_rule_uids"]])


if __name__ == "__main__":
    unittest.main()
