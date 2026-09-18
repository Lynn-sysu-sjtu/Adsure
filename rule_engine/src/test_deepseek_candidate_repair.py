# -*- coding: utf-8 -*-
import json
import unittest

from deepseek_candidate_repair import repair_candidate


class FakeRepairClient:
    def create_chat_completion(self, messages, model, temperature, response_format):
        self.messages = messages
        uid = json.loads(messages[1]["content"])["rule"]["rule_uid"]
        payload = {"rule_uid": uid, "issue_candidates": [{"namespace": "GAME", "category_key": "CONTENT", "issue_key": "PUBLIC_MORALS", "name": "公序良俗", "definition": "损害社会公序良俗的内容", "in_scope": ["侮辱贬损"], "out_of_scope": ["中性表达"], "claim_types": ["public_morals"], "relationship": "primary"}], "elements": [{"element_id": "harmful_expression", "description": "存在不良表达", "required": True, "allowed_evidence_sources": ["content"]}], "evidence_policy": {"content": "can_confirm", "context": "scope_only", "fact_state": "not_allowed", "llm_signal": "candidate_only"}, "default_terminal_outcome": "confirmed_violation", "proactive_check": None, "quality_flags": [], "confidence": "high", "reason": "规则直接规制不良表达。"}
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


class DeepSeekCandidateRepairTests(unittest.TestCase):
    def test_repair_requires_deepseek_to_choose_exactly_one_primary(self):
        record = {"source_file": "游戏/example.json", "rule": {"rule_uid": "RUID-GAME-1", "rule_id": "G1", "title": "公序良俗", "dimension": "公序良俗", "legal_basis": [{"quote": "原文"}]}}
        client = FakeRepairClient(); result = repair_candidate(client, record)
        self.assertEqual("primary", result["issue_candidates"][0]["relationship"])
        self.assertIn("有且仅有一个", client.messages[0]["content"])
        self.assertEqual("deepseek-chat", result["_repair_model"])


if __name__ == "__main__": unittest.main()
