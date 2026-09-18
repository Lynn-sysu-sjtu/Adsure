# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from legal_asset_drafts import build_jsonbase_snapshot, load_runtime_legal_assets, validate_draft_assets


ROOT = Path(__file__).resolve().parents[1]


def _review():
    return {"status": "pending", "reviewer": None, "reviewed_at": None, "notes": None}


def _policy():
    return {"content": "can_confirm", "context": "scope_only", "fact_state": "support_or_refute", "llm_signal": "candidate_only"}


def _rules():
    return [{"rule_uid": "RUID-HF-1", "rule_id": "HF-001", "legal_basis": [{"source_id": "AL", "article": "第八条", "quote": "广告应当真实。"}]}]


def _issues(status="draft"):
    return {"schema_version": "0.1", "asset_status": status, "generated_at": "2026-09-08T00:00:00+08:00", "source_snapshot": {"rule_count": 1, "jsonbase_sha256": "a" * 64}, "issues": [{"issue_id": "HF.CLAIM.DISEASE_TREATMENT", "name": "保健食品疾病治疗宣称", "track": "保健食品", "parent_issue_id": None, "issue_path": ["HF", "CLAIM", "DISEASE_TREATMENT"], "definition": "识别疾病预防或治疗宣称。", "in_scope": ["宣称治疗疾病"], "out_of_scope": ["合规警示语"], "claim_types": ["disease_treatment"], "default_evidence_policy": _policy(), "candidate_rule_uids": ["RUID-HF-1"], "review": _review(), "generation": {"model": "deepseek-chat", "prompt_version": "legal_issue_candidate_v1", "confidence": "high", "reason": "规则明确禁止疾病治疗宣称。"}}]}


def _mappings(status="draft"):
    return {"schema_version": "0.1", "asset_status": status, "mappings": [{"rule_uid": "RUID-HF-1", "rule_id": "HF-001", "source_file": "保健食品/example.json", "primary_issue_id": "HF.CLAIM.DISEASE_TREATMENT", "secondary_issue_ids": [], "elements": [{"element_id": "disease_treatment_claim", "description": "正文表达疾病治疗作用", "required": True, "allowed_evidence_sources": ["content"]}], "evidence_policy": _policy(), "default_terminal_outcome": "confirmed_violation", "proactive_check_ids": [], "mapping_confidence": "high", "mapping_reason": "正文即可确认该禁止性表达。", "review": _review()}]}


def _checks(status="draft"):
    return {"schema_version": "0.1", "asset_status": status, "checks": [{"check_id": "HF.AD_REVIEW.PRE_APPROVAL_CHECK", "name": "保健食品广告审查批准核验", "check_type": "fact_verification", "track": "保健食品", "trigger_issue_ids": ["HF.CLAIM.DISEASE_TREATMENT"], "applicability": {"industries": ["保健食品"], "platforms": [], "material_types": []}, "trigger_conditions": {"all": ["health_food_context"], "any": [], "exclude": []}, "requirement": "核验是否取得广告审查批准文件。", "required_materials": ["广告审查批准文件"], "basis_rule_uids": ["RUID-HF-1"], "default_status": "需要核验", "default_severity": "高", "review": _review()}]}


class DraftSchemaTests(unittest.TestCase):
    def test_examples_conform_to_checked_in_schemas(self):
        for name, payload in (("legal_issue_directory_draft_schema.json", _issues()), ("rule_issue_mapping_draft_schema.json", _mappings()), ("proactive_check_directory_draft_schema.json", _checks())):
            Draft202012Validator(json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))).validate(payload)


class DraftAssetValidationTests(unittest.TestCase):
    def test_valid_cross_references_pass(self):
        self.assertEqual([], validate_draft_assets(_issues(), _mappings(), _checks(), _rules())["errors"])

    def test_unknown_rule_uid_is_rejected(self):
        asset = _issues(); asset["issues"][0]["candidate_rule_uids"] = ["RUID-MISSING"]
        self.assertTrue(any("RUID-MISSING" in value for value in validate_draft_assets(asset, _mappings(), _checks(), _rules())["errors"]))

    def test_issue_tree_cycle_is_rejected(self):
        asset = _issues(); asset["issues"][0]["parent_issue_id"] = "HF.CLAIM.DISEASE_TREATMENT"
        self.assertTrue(any("cycle" in value.lower() for value in validate_draft_assets(asset, _mappings(), _checks(), _rules())["errors"]))

    def test_proactive_check_requires_rule_with_legal_basis(self):
        rules = _rules(); rules[0]["legal_basis"] = []
        self.assertTrue(any("legal_basis" in value for value in validate_draft_assets(_issues(), _mappings(), _checks(), rules)["errors"]))

    def test_approved_record_requires_human_reviewer_and_time(self):
        asset = _issues("approved"); asset["issues"][0]["review"]["status"] = "approved"
        self.assertTrue(any("reviewer" in value for value in validate_draft_assets(asset, _mappings(), _checks(), _rules())["errors"]))

    def test_runtime_loader_rejects_draft_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, payload in (("legal_issue_directory_draft.json", _issues()), ("rule_issue_mapping_draft.json", _mappings()), ("proactive_check_directory_draft.json", _checks())):
                (root / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "draft"):
                load_runtime_legal_assets(root)


class JsonbaseSnapshotTests(unittest.TestCase):
    def test_snapshot_changes_when_rule_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / "规则.json"
            path.write_text('{"rules": []}', encoding="utf-8"); before = build_jsonbase_snapshot(root)
            path.write_text('{"rules": [{"rule_uid": "R1"}]}', encoding="utf-8"); after = build_jsonbase_snapshot(root)
            self.assertNotEqual(before["jsonbase_sha256"], after["jsonbase_sha256"])
            self.assertEqual(1, before["file_count"])


if __name__ == "__main__":
    unittest.main()
