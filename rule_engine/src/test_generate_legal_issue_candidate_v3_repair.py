# -*- coding: utf-8 -*-
import json
import unittest

from generate_legal_issue_candidates import _call_deepseek


def _rule():
    return {
        "rule_uid": "RUID-COSM-1",
        "rule_id": "COSM-1",
        "title": "美白功效宣称需通过人体功效评价试验",
        "source_type": "行政规范性文件",
        "applies_to": {"industries": ["美妆"]},
        "legal_basis": [{"text": "祛斑美白功效宣称需通过人体功效评价试验。"}],
        "rule_applicability": {"reason": "适用于祛斑美白功效宣称。"},
    }


def _candidate(evidence):
    return {
        "rule_uid": "RUID-COSM-1",
        "issue_candidates": [{
            "namespace": "COSM", "category_key": "EFFICACY", "issue_key": "WHITENING",
            "name": "美白功效评价", "definition": "核验美白功效评价。",
            "in_scope": ["美白宣称"], "out_of_scope": [], "claim_types": ["whitening"],
            "relationship": "primary",
        }],
        "elements": [{"element_id": "evaluation", "description": "完成人体功效评价试验", "required": True, "allowed_evidence_sources": ["fact_state"]}],
        "evidence_policy": {"content": "trigger_only", "context": "scope_only", "fact_state": "required_to_confirm", "llm_signal": "candidate_only"},
        "default_terminal_outcome": "evidence_required",
        "proactive_check": {
            "check_key": "EFFICACY_EVALUATION", "name": "功效评价核验",
            "check_type": "fact_verification",
            "applicability": {"industries": ["美妆"], "platforms": [], "material_types": []},
            "trigger_conditions": {"all": [], "any": [], "exclude": []},
            "requirement": "核验人体功效评价试验", "required_materials": ["人体功效评价报告"],
            "default_severity": "高",
            "core_support": [{"source_field": "legal_basis", "evidence": evidence}],
        },
        "quality_flags": [], "confidence": "high", "reason": "依据规则原文。",
    }


class FakeRepairClient:
    def __init__(self):
        self.calls = []

    def create_chat_completion(self, messages, model, temperature, response_format):
        self.calls.append(messages)
        candidate = _candidate("概括后的非原文") if len(self.calls) == 1 else _candidate("祛斑美白功效宣称需通过人体功效评价试验。")
        return {"choices": [{"message": {"content": json.dumps(candidate, ensure_ascii=False)}}]}


class CandidateV3RepairTests(unittest.TestCase):
    def test_invalid_support_is_repaired_by_deepseek_before_acceptance(self):
        client = FakeRepairClient()
        candidate = _call_deepseek(client, {"rule": _rule(), "source_file": "美妆/example.json"})
        self.assertEqual(2, len(client.calls))
        self.assertEqual("祛斑美白功效宣称需通过人体功效评价试验。", candidate["proactive_check"]["core_support"][0]["evidence"])
        repair_prompt = client.calls[1][-1]["content"]
        self.assertIn("确定性校验失败", repair_prompt)
        self.assertNotIn("fact_check", json.dumps(client.calls[1], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
