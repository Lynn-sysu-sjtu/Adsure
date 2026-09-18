# -*- coding: utf-8 -*-
import json
import unittest

from generate_legal_issue_candidates import PROMPT_VERSION
from legal_issue_candidate_pipeline import build_candidate_messages, parse_candidate_response


def _rule():
    return {
        "rule_uid": "RUID-GAME-1", "rule_id": "GAME-1", "title": "游戏版号核验",
        "dimension": "平台准入", "industry": "游戏", "platform": "抖音",
        "source_type": "平台规则", "applies_to": {"industries": ["游戏"]},
        "legal_basis": [{"source_id": "PLATFORM", "text": "需提供版号。"}],
        "detection": {"semantic_criteria": ["版号"]}, "recall": {"trigger_layer": "fact"},
        "rule_applicability": {"type": "明确适用型"},
        "fact_check": {"required_materials": ["游戏版号"]},
        "legal_attention": {"default_route": "operator_fixable"},
    }


def _candidate():
    return {
        "rule_uid": "RUID-GAME-1",
        "issue_candidates": [{
            "namespace": "GAME", "category_key": "ACCESS", "issue_key": "LICENSE",
            "name": "游戏版号核验", "definition": "核验游戏推广所需版号。",
            "in_scope": ["游戏商业推广"], "out_of_scope": ["非游戏内容"],
            "claim_types": ["game_license"], "relationship": "primary",
        }],
        "elements": [{"element_id": "game_license", "description": "取得游戏版号", "required": True, "allowed_evidence_sources": ["fact_state"]}],
        "evidence_policy": {"content": "trigger_only", "context": "scope_only", "fact_state": "required_to_confirm", "llm_signal": "candidate_only"},
        "default_terminal_outcome": "evidence_required", "proactive_check": None,
        "quality_flags": [], "confidence": "high", "reason": "标题、法源和适用范围均直接支持。",
    }


class LegalIssueCandidatePromptV3CompatibilityTests(unittest.TestCase):
    def test_prompt_version_is_v3(self):
        self.assertEqual("legal_issue_candidate_v3", PROMPT_VERSION)

    def test_source_type_is_explicit_core_evidence(self):
        messages = build_candidate_messages(_rule(), "游戏/example.json")
        payload = json.loads(messages[1]["content"])
        self.assertEqual("平台规则", payload["rule"]["source_type"])
        self.assertIn("source_type", payload["evidence_tiers"]["core"])

    def test_fact_check_is_excluded_from_model_input(self):
        messages = build_candidate_messages(_rule(), "游戏/example.json")
        payload = json.loads(messages[1]["content"])
        self.assertNotIn("fact_check", payload["rule"])
        self.assertNotIn("fact_check", messages[0]["content"])

    def test_prompt_locks_namespace_primary_and_proactive_boundaries(self):
        system = build_candidate_messages(_rule(), "游戏/example.json")[0]["content"]
        self.assertIn("有且仅有一个", system)
        self.assertIn("游戏版号", system)
        self.assertIn("proactive_check必须为null", system)

    def test_parser_accepts_quality_flags(self):
        parsed = parse_candidate_response(_candidate(), "RUID-GAME-1")
        self.assertEqual([], parsed["quality_flags"])

    def test_parser_requires_quality_flags(self):
        payload = _candidate(); payload.pop("quality_flags")
        with self.assertRaisesRegex(ValueError, "quality_flags"):
            parse_candidate_response(payload, "RUID-GAME-1")


if __name__ == "__main__": unittest.main()
