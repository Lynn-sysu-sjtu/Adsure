# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from legal_issue_smoke_runner import run_curated_smoke


class FakeClient:
    def __init__(self): self.uids = []
    def create_chat_completion(self, messages, model, temperature, response_format):
        rule = json.loads(messages[1]["content"])["rule"]; uid = rule["rule_uid"]; namespace = uid.split("-")[1]; self.uids.append(uid)
        payload = {"rule_uid": uid, "issue_candidates": [{"namespace": namespace, "category_key": "CLAIM", "issue_key": uid.replace("RUID-", ""), "name": "候选问题", "definition": "候选问题定义", "in_scope": ["纳入"], "out_of_scope": ["排除"], "claim_types": ["claim"], "relationship": "primary"}], "elements": [{"element_id": "claim", "description": "存在宣称", "required": True, "allowed_evidence_sources": ["content"]}], "evidence_policy": {"content": "can_confirm", "context": "scope_only", "fact_state": "support_or_refute", "llm_signal": "candidate_only"}, "default_terminal_outcome": "confirmed_violation", "proactive_check": None, "quality_flags": [], "confidence": "high", "reason": "依据输入规则。"}
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def _rule(uid, track, title):
    return {"rule_uid": uid, "rule_id": uid, "title": title, "dimension": title, "industry": track, "platform": "", "source_type": "法律", "applies_to": {"industries": [track]}, "legal_basis": [{"text": "原文"}], "detection": {}, "recall": {}, "rule_applicability": {}, "fact_check": {}, "legal_attention": {}}


class CuratedSmokeRunnerTests(unittest.TestCase):
    def test_uses_curated_topics_and_writes_validation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); topics = {"游戏": ("抽卡概率", "游戏版号", "未成年人充值", "代言真实体验", "公序良俗"), "美妆": ("医疗治疗", "功效超备案", "特殊化妆品", "实验数据", "达人推荐"), "保健食品": ("疾病治疗", "替代药物", "功效保证", "广告审查批准", "警示语")}; prefixes = {"游戏": "GAME", "美妆": "COSM", "保健食品": "HF"}
            for track, titles in topics.items():
                folder = root / "jsonbase" / track; folder.mkdir(parents=True); rules = [_rule(f"RUID-{prefixes[track]}-{i}", track, title) for i, title in enumerate(titles, 1)]; (folder / "rules.json").write_text(json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8")
            summary = run_curated_smoke(root / "jsonbase", root / "assets", root / "reports", client=FakeClient(), per_track=5)
            self.assertEqual(15, summary["successful_rule_count"]); self.assertTrue((root / "reports" / "validation_report.json").exists())


if __name__ == "__main__": unittest.main()
