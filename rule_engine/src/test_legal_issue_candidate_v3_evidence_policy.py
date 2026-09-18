# -*- coding: utf-8 -*-
import unittest

from legal_issue_candidate_pipeline import parse_candidate_response


def _candidate():
    return {
        "rule_uid": "RUID-1",
        "issue_candidates": [{
            "namespace": "GEN", "category_key": "CONTENT", "issue_key": "CLAIM",
            "name": "宣称问题", "definition": "宣称问题", "in_scope": [],
            "out_of_scope": [], "claim_types": ["claim"], "relationship": "primary",
        }],
        "elements": [{"element_id": "claim", "description": "存在宣称", "required": True, "allowed_evidence_sources": ["content"]}],
        "evidence_policy": {"content": "can_confirm", "context": "scope_only", "fact_state": "not_allowed", "llm_signal": "not_allowed"},
        "default_terminal_outcome": "confirmed_violation", "proactive_check": None,
        "quality_flags": [], "confidence": "high", "reason": "依据规则。",
    }


class CandidateV3EvidencePolicyTests(unittest.TestCase):
    def test_rejects_llm_signal_other_than_candidate_only(self):
        with self.assertRaisesRegex(ValueError, "llm_signal"):
            parse_candidate_response(_candidate(), "RUID-1")


if __name__ == "__main__":
    unittest.main()
