# -*- coding: utf-8 -*-
import json
import unittest

from deepseek_full_failure_repair import repair_with_retries


def _candidate(proactive):
    return {
        "rule_uid": "RUID-1",
        "issue_candidates": [{
            "namespace": "GAME", "category_key": "CONTENT", "issue_key": "FALSE_EFFECT",
            "name": "虚构效果", "definition": "虚构效果", "in_scope": ["虚构效果"],
            "out_of_scope": [], "claim_types": ["false_effect"], "relationship": "primary",
        }],
        "elements": [{"element_id": "effect", "description": "虚构效果", "required": True, "allowed_evidence_sources": ["content"]}],
        "evidence_policy": {"content": "can_confirm", "context": "scope_only", "fact_state": "not_allowed", "llm_signal": "candidate_only"},
        "default_terminal_outcome": "confirmed_violation",
        "proactive_check": proactive,
        "quality_flags": [], "confidence": "high", "reason": "规则直接规制。",
    }


class FakeClient:
    def __init__(self):
        self.calls = []

    def create_chat_completion(self, messages, model, temperature, response_format):
        self.calls.append(messages)
        proactive = {
            "name": "概率核验", "trigger_conditions": {"all": [], "any": ["概率"], "exclude": []},
            "requirement": "核验概率", "required_materials": ["概率数据"],
            "core_support": [{"source_field": "title", "evidence": "虚构效果"}],
        } if len(self.calls) == 1 else None
        return {"choices": [{"message": {"content": json.dumps(_candidate(proactive), ensure_ascii=False)}}]}


class FullFailureRepairRetryTests(unittest.TestCase):
    def test_second_attempt_receives_latest_gate_error(self):
        record = {
            "rule": {
                "rule_uid": "RUID-1", "title": "虚构效果",
                "legal_basis": [{"text": "不得虚构效果。"}],
                "applies_to": {"industries": ["游戏"]}, "rule_applicability": {},
            },
            "source_file": "游戏/example.json",
        }
        client = FakeClient()
        candidate = repair_with_retries(client, record, "issue keys must be stable ASCII identifiers")
        self.assertIsNone(candidate["proactive_check"])
        self.assertEqual(2, len(client.calls))
        self.assertIn("unsupported proactive topic", client.calls[1][-1]["content"])


if __name__ == "__main__":
    unittest.main()
