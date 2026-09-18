# -*- coding: utf-8 -*-
import json
import unittest

from generate_legal_issue_candidates import PROMPT_VERSION
from legal_issue_candidate_pipeline import build_candidate_messages
from legal_issue_candidate_v3_gate import validate_candidate_core_support


def _rule():
    return {
        "rule_uid": "RUID-GAME-1", "rule_id": "GAME-1", "title": "游戏推广应提供游戏版号",
        "dimension": "平台准入", "industry": "游戏", "platform": "小红书", "source_type": "平台规则",
        "applies_to": {"industries": ["游戏"]}, "legal_basis": [{"text": "游戏推广需提供游戏版号。"}],
        "detection": {"semantic_criteria": ["版号"]}, "recall": {"trigger_layer": "fact"},
        "rule_applicability": {"reason": "发布游戏广告前需要核验版号"},
        "fact_check": {"required_materials": ["奖池概率", "保底机制"]}, "legal_attention": {},
    }


def _candidate(evidence="游戏推广需提供游戏版号。", field="legal_basis"):
    return {
        "rule_uid": "RUID-GAME-1", "issue_candidates": [{"namespace": "GAME", "category_key": "ACCESS", "issue_key": "LICENSE", "name": "游戏版号核验", "definition": "核验游戏版号", "in_scope": ["游戏推广"], "out_of_scope": [], "claim_types": ["game_license"], "relationship": "primary"}],
        "elements": [{"element_id": "license", "description": "具有游戏版号", "required": True, "allowed_evidence_sources": ["fact_state"]}],
        "evidence_policy": {"content": "trigger_only", "context": "scope_only", "fact_state": "required_to_confirm", "llm_signal": "candidate_only"},
        "default_terminal_outcome": "evidence_required",
        "proactive_check": {"check_key": "LICENSE_CHECK", "name": "游戏版号核验", "check_type": "qualification", "applicability": {"industries": ["游戏"], "platforms": [], "material_types": []}, "trigger_conditions": {"all": [], "any": [], "exclude": []}, "requirement": "核验游戏版号", "required_materials": ["游戏版号"], "default_severity": "高", "core_support": [{"source_field": field, "evidence": evidence}]},
        "quality_flags": [], "confidence": "high", "reason": "核心依据直接要求游戏版号。",
    }


class CandidatePromptV3Tests(unittest.TestCase):
    def test_prompt_version_is_v3(self):
        self.assertEqual("legal_issue_candidate_v3", PROMPT_VERSION)

    def test_fact_check_is_not_sent_to_deepseek(self):
        payload = json.loads(build_candidate_messages(_rule(), "游戏/example.json")[1]["content"])
        self.assertNotIn("fact_check", payload["rule"])
        self.assertNotIn("fact_check", payload["evidence_tiers"].get("unreviewed_hint", []))

    def test_prompt_requires_exact_core_support_for_proactive_check(self):
        messages = build_candidate_messages(_rule(), "游戏/example.json")
        self.assertIn("core_support", messages[0]["content"])
        self.assertIn("逐字存在", messages[0]["content"])


class CandidateCoreSupportGateTests(unittest.TestCase):
    def test_accepts_exact_quote_from_allowed_core_field(self):
        self.assertEqual([], validate_candidate_core_support(_candidate(), _rule()))

    def test_rejects_quote_found_only_in_fact_check(self):
        errors = validate_candidate_core_support(_candidate("奖池概率", "legal_basis"), _rule())
        self.assertTrue(any("core_support" in item for item in errors))

    def test_rejects_fact_check_as_support_field(self):
        errors = validate_candidate_core_support(_candidate("奖池概率", "fact_check"), _rule())
        self.assertTrue(any("source_field" in item for item in errors))

    def test_rejects_proactive_check_without_support(self):
        candidate = _candidate(); candidate["proactive_check"].pop("core_support")
        errors = validate_candidate_core_support(candidate, _rule())
        self.assertTrue(any("core_support" in item for item in errors))


if __name__ == "__main__": unittest.main()
