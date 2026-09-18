# -*- coding: utf-8 -*-
import unittest

from legal_issue_candidate_pipeline import parse_candidate_response


class CandidateV3RequiredFieldTests(unittest.TestCase):
    def test_rejects_issue_candidate_without_definition(self):
        candidate = {
            "rule_uid": "RUID-1",
            "issue_candidates": [{
                "namespace": "GEN", "category_key": "CONTENT", "issue_key": "CLAIM",
                "name": "宣称问题", "in_scope": [], "out_of_scope": [],
                "claim_types": ["claim"], "relationship": "primary",
            }],
            "elements": [{"element_id": "claim", "description": "存在宣称", "required": True, "allowed_evidence_sources": ["content"]}],
            "evidence_policy": {"content": "can_confirm", "context": "scope_only", "fact_state": "not_allowed", "llm_signal": "candidate_only"},
            "default_terminal_outcome": "confirmed_violation", "proactive_check": None,
            "quality_flags": [], "confidence": "high", "reason": "依据规则。",
        }
        with self.assertRaisesRegex(ValueError, "definition"):
            parse_candidate_response(candidate, "RUID-1")


if __name__ == "__main__":
    unittest.main()
