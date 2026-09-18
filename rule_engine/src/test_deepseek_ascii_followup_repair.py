# -*- coding: utf-8 -*-
import json
import unittest

from deepseek_full_failure_repair import repair_candidate


def _candidate(category_key, issue_key):
    return {
        "rule_uid": "RUID-1",
        "issue_candidates": [{
            "namespace": "COSM", "category_key": category_key, "issue_key": issue_key,
            "name": "功效承诺", "definition": "无依据功效承诺",
            "in_scope": ["功效承诺"], "out_of_scope": [],
            "claim_types": ["efficacy_claim"], "relationship": "primary",
        }],
        "elements": [{"element_id": "claim", "description": "功效承诺", "required": True, "allowed_evidence_sources": ["content"]}],
        "evidence_policy": {"content": "can_confirm", "context": "scope_only", "fact_state": "support_or_refute", "llm_signal": "candidate_only"},
        "default_terminal_outcome": "confirmed_violation", "proactive_check": None,
        "quality_flags": [], "confidence": "high", "reason": "依据规则。",
    }


class FakeAsciiFollowupClient:
    def __init__(self):
        self.calls = []

    def create_chat_completion(self, messages, model, temperature, response_format):
        self.calls.append(messages)
        payload = _candidate("功效宣称", "无依据效果承诺") if len(self.calls) == 1 else _candidate("EFFICACY_CLAIM", "UNSUPPORTED_EFFECT_PROMISE")
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


class AsciiFollowupRepairTests(unittest.TestCase):
    def test_ascii_parse_failure_gets_raw_candidate_followup(self):
        client = FakeAsciiFollowupClient()
        record = {
            "rule": {
                "rule_uid": "RUID-1", "title": "无依据效果承诺",
                "legal_basis": [{"text": "不得作无依据效果承诺。"}],
                "applies_to": {"industries": ["美妆"]}, "rule_applicability": {},
            },
            "source_file": "美妆/example.json",
        }
        candidate = repair_candidate(client, record, "issue keys must be stable ASCII identifiers")
        self.assertEqual(2, len(client.calls))
        self.assertEqual("EFFICACY_CLAIM", candidate["issue_candidates"][0]["category_key"])
        self.assertIn("上一版完整JSON", client.calls[1][-1]["content"])


if __name__ == "__main__":
    unittest.main()
