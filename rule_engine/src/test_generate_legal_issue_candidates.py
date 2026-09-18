# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from generate_legal_issue_candidates import load_rule_records, run_candidate_generation


def _rule(uid, track, dimension):
    return {"rule_uid": uid, "rule_id": uid, "title": dimension, "dimension": dimension, "industry": track, "platform": "", "source_type": "法律", "applies_to": {"industries": [track], "platforms": []}, "legal_basis": [{"source_id": "AL", "article": "第一条", "quote": "原文"}], "detection": {"semantic_criteria": [dimension]}, "recall": {"trigger_layer": "content"}, "rule_applicability": {}, "fact_check": {"required": False}, "legal_attention": {}}


def _response(uid, namespace):
    return {"rule_uid": uid, "issue_candidates": [{"namespace": namespace, "category_key": "CLAIM", "issue_key": uid.replace("RUID-", ""), "name": "候选问题", "definition": "候选问题定义", "in_scope": ["纳入"], "out_of_scope": ["排除"], "claim_types": ["claim"], "relationship": "primary"}], "elements": [{"element_id": "claim", "description": "存在相关宣称", "required": True, "allowed_evidence_sources": ["content"]}], "evidence_policy": {"content": "can_confirm", "context": "scope_only", "fact_state": "support_or_refute", "llm_signal": "candidate_only"}, "default_terminal_outcome": "confirmed_violation", "proactive_check": None, "quality_flags": [], "confidence": "high", "reason": "依据输入规则形成候选。"}


class FakeDeepSeekClient:
    def __init__(self): self.calls = []
    def create_chat_completion(self, messages, model, temperature, response_format):
        uid = json.loads(messages[1]["content"])["rule"]["rule_uid"]; namespace = uid.split("-")[1]
        self.calls.append((uid, model)); return {"choices": [{"message": {"content": json.dumps(_response(uid, namespace), ensure_ascii=False)}}]}


class CandidateGenerationTests(unittest.TestCase):
    def _jsonbase(self, root, count=5):
        jsonbase = root / "jsonbase"
        for track, prefix in (("游戏", "GAME"), ("美妆", "COSM"), ("保健食品", "HF")):
            folder = jsonbase / track; folder.mkdir(parents=True)
            rules = [_rule(f"RUID-{prefix}-{index}", track, chr(64 + index)) for index in range(1, count + 1)]
            (folder / "规则.json").write_text(json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8")
        return jsonbase

    def test_generates_v2_deepseek_drafts_without_changing_jsonbase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); jsonbase = self._jsonbase(root); before = {p: p.read_bytes() for p in jsonbase.rglob("*.json")}; client = FakeDeepSeekClient()
            summary = run_candidate_generation(jsonbase, root / "assets", root / "reports", client=client, per_track=5)
            self.assertEqual(before, {p: p.read_bytes() for p in jsonbase.rglob("*.json")})
            self.assertEqual(15, summary["successful_rule_count"]); self.assertEqual({"deepseek-chat"}, {model for _, model in client.calls})

    def test_resume_reuses_v2_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); jsonbase = self._jsonbase(root, count=1); first = FakeDeepSeekClient()
            run_candidate_generation(jsonbase, root / "assets", root / "reports", client=first, per_track=1)
            second = FakeDeepSeekClient(); run_candidate_generation(jsonbase, root / "assets", root / "reports", client=second, per_track=1)
            self.assertEqual(3, len(first.calls)); self.assertEqual(0, len(second.calls))


class RuleRecordLoadingTests(unittest.TestCase):
    def test_loads_three_tracks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for track, prefix in (("游戏", "GAME"), ("美妆", "COSM"), ("保健食品", "HF")):
                folder = root / track; folder.mkdir(); (folder / "规则.json").write_text(json.dumps({"rules": [_rule(f"RUID-{prefix}-1", track, "维度")]}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual({"游戏", "美妆", "保健食品"}, {item["track"] for item in load_rule_records(root)})


if __name__ == "__main__": unittest.main()
