# -*- coding: utf-8 -*-

import json
import tempfile
import unittest
from pathlib import Path

from all_primary_issue_fingerprint_review import (
    build_exact_norm_groups,
    build_fingerprint_messages,
    compile_global_audit,
    call_json_checkpoint,
    compile_root_assets,
    records_for_root,
    source_details,
    validate_fingerprint_payload,
    validate_skeleton_payload,
)


def record(uid, track="游戏", text="广告不得含有虚假内容。"):
    return {
        "track": track,
        "source_file": f"{track}/source.json",
        "legal_sources": [{"id": "AL", "name": "中华人民共和国广告法", "type": "法律", "legal_level": 1}],
        "rule": {
            "rule_uid": uid,
            "rule_id": uid,
            "title": "禁止虚假宣传",
            "source_type": "法律",
            "legal_basis": [{"source_id": "AL", "article": "第四条", "text": text, "legal_level": 1}],
            "applies_to": {},
            "rule_applicability": {},
        },
    }


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def create_chat_completion(self, messages, **kwargs):
        self.calls += 1
        return {"choices": [{"message": {"content": json.dumps(self.payload, ensure_ascii=False)}}]}


class AllPrimaryIssueReviewTests(unittest.TestCase):
    def test_records_for_root_uses_primary_mapping_once(self):
        records = [record("r1"), record("r2"), record("r3")]
        mappings = [
            {"rule_uid": "r1", "primary_issue_id": "TRUTHFULNESS.A"},
            {"rule_uid": "r2", "primary_issue_id": "ENDORSEMENT_REVIEW.A"},
            {"rule_uid": "r3", "primary_issue_id": "TRUTHFULNESS.B"},
        ]
        selected = records_for_root(records, mappings, "TRUTHFULNESS")
        self.assertEqual([item["rule"]["rule_uid"] for item in selected], ["r1", "r3"])

    def test_skeleton_validation_requires_allowed_l2_and_unique_l3(self):
        payload = {"nodes": [
            {"issue_id": "TRUTHFULNESS.FACT.FALSE", "parent_issue_id": "TRUTHFULNESS.FACT", "name": "虚构事实", "definition": "虚构或捏造事实", "confidence": "high", "reason": "依据旧问题归并"},
        ]}
        result = validate_skeleton_payload(payload, "TRUTHFULNESS", {"TRUTHFULNESS.FACT"})
        self.assertEqual(result[0]["issue_id"], "TRUTHFULNESS.FACT.FALSE")
        with self.assertRaises(ValueError):
            validate_skeleton_payload(payload, "TRUTHFULNESS", {"TRUTHFULNESS.OTHER"})

    def test_fingerprint_prompt_contains_original_text_and_marks_track_weak(self):
        messages = build_fingerprint_messages(
            "TRUTHFULNESS", "宣传真实性",
            [{"issue_id": "TRUTHFULNESS.FACT.FALSE", "name": "虚构事实", "definition": "虚构事实"}],
            [record("r1")],
        )
        content = messages[1]["content"]
        self.assertIn("广告不得含有虚假内容", content)
        self.assertIn("track_hint_only", content)

    def test_fingerprint_validation_enforces_uid_and_issue_coverage(self):
        payload = {"fingerprints": [{
            "rule_uid": "r1", "target_issue_id": "TRUTHFULNESS.FACT.FALSE",
            "canonical_problem_name": "虚假宣传", "regulated_action": "false_claim",
            "legal_effect": "prohibited", "actor_scope": [], "object_scope": ["general_advertising"],
            "platform_scope": [], "evidence_requirement": "content", "source_scope_conflict": False,
            "root_scope_conflict": False, "suggested_root_id": "TRUTHFULNESS",
            "confidence": "high", "reason": "原文直接禁止虚假内容",
        }]}
        result = validate_fingerprint_payload(payload, ["r1"], {"TRUTHFULNESS.FACT.FALSE"})
        self.assertEqual(result[0]["rule_uid"], "r1")
        with self.assertRaises(ValueError):
            validate_fingerprint_payload(payload, ["r1", "r2"], {"TRUTHFULNESS.FACT.FALSE"})

    def test_exact_norm_groups_use_source_article_text_and_effect(self):
        first = record("r1", track="游戏")
        second = record("r2", track="美妆")
        fps = {
            "r1": {"legal_effect": "prohibited", "source_scope_conflict": False},
            "r2": {"legal_effect": "prohibited", "source_scope_conflict": True},
        }
        groups, uid_to_key = build_exact_norm_groups({"r1": first, "r2": second}, fps)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["duplicate_count"], 2)
        self.assertEqual(uid_to_key["r1"], uid_to_key["r2"])

    def test_compile_keeps_proactive_candidate_out_of_legal_node_rules(self):
        skeleton = [
            {"issue_id": "EVIDENCE_FACT.QUAL.DOCTOR", "parent_issue_id": "EVIDENCE_FACT.QUAL", "name": "医生证明", "definition": "核验医生证明", "confidence": "high", "reason": ""},
            {"issue_id": "EVIDENCE_FACT.QUAL.UNUSED", "parent_issue_id": "EVIDENCE_FACT.QUAL", "name": "空问题", "definition": "没有规则来源", "confidence": "low", "reason": ""},
        ]
        fp = {
            "rule_uid": "r1", "target_issue_id": "EVIDENCE_FACT.QUAL.DOCTOR", "canonical_problem_name": "医生证明",
            "regulated_action": "doctor_proof", "legal_effect": "evidence_required", "actor_scope": [],
            "object_scope": ["general_food"], "platform_scope": ["xiaohongshu"], "evidence_requirement": "fact",
            "source_scope_conflict": False, "root_scope_conflict": False, "suggested_root_id": "EVIDENCE_FACT",
            "confidence": "high", "reason": "需要提交证明",
        }
        assets = compile_root_assets("EVIDENCE_FACT", "证明材料与事实核验", [], skeleton, [record("r1")], [fp])
        self.assertEqual(assets["mappings"][0]["mapping_type"], "proactive_check")
        self.assertEqual(assets["nodes"][0]["rule_uids"], [])
        self.assertEqual([item["issue_id"] for item in assets["nodes"]], ["EVIDENCE_FACT.QUAL.DOCTOR"])

    def test_checkpoint_reuses_input_hash(self):
        client = FakeClient({"value": 1})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            first = call_json_checkpoint(client, [{"role": "user", "content": "x"}], path, "v1")
            second = call_json_checkpoint(client, [{"role": "user", "content": "x"}], path, "v1")
        self.assertEqual(first, second)
        self.assertEqual(client.calls, 1)


    def test_global_audit_finds_cross_root_duplicates_and_coverage_gap(self):
        first = record("r1", track="游戏")
        second = record("r2", track="美妆")
        mappings = []
        for root_id, source_record in (("TRUTHFULNESS", first), ("CLAIM_EXPRESSION", second)):
            uid = source_record["rule"]["rule_uid"]
            mappings.append({
                "rule_uid": uid,
                "rule_id": uid,
                "rule_title": source_record["rule"]["title"],
                "root_id": root_id,
                "issue_id": root_id + ".FACT.FALSE",
                "mapping_type": "legal_issue",
                "track": source_record["track"],
                "source_file": source_record["source_file"],
                "source_details": source_details(source_record),
                "fingerprint": {
                    "legal_effect": "prohibited",
                    "source_scope_conflict": False,
                    "root_scope_conflict": root_id == "CLAIM_EXPRESSION",
                    "suggested_root_id": "TRUTHFULNESS",
                    "confidence": "high",
                    "object_scope": ["general_advertising"],
                    "evidence_requirement": "content",
                },
            })
        endorsement_occurrence = dict(mappings[0])
        endorsement_occurrence["root_id"] = "ENDORSEMENT_REVIEW"
        endorsement_occurrence["issue_id"] = "ENDORSEMENT_REVIEW.FALSE_AD"
        mappings.append(endorsement_occurrence)
        result = compile_global_audit(
            mappings,
            expected_mappings=[
                {"rule_uid": "r1", "primary_issue_id": "TRUTHFULNESS.FACT"},
                {"rule_uid": "r2", "primary_issue_id": "CLAIM_EXPRESSION.FACT"},
                {"rule_uid": "r3", "primary_issue_id": "ENDORSEMENT_REVIEW.OTHER"},
            ],
            records_by_uid={"r1": first, "r2": second, "r3": record("r3")},
        )
        self.assertEqual(result["coverage"]["processed_count"], 2)
        self.assertEqual(result["coverage"]["missing_rule_uids"], ["r3"])
        self.assertEqual(len(result["duplicate_groups"]), 1)
        self.assertEqual(result["duplicate_groups"][0]["root_ids"], ["CLAIM_EXPRESSION", "TRUTHFULNESS"])
        self.assertEqual([item["rule_uid"] for item in result["root_conflicts"]], ["r2"])
        self.assertEqual(result["cross_root_overlaps"][0]["rule_uid"], "r1")
        self.assertEqual(result["cross_root_overlaps"][0]["selected_root_id"], "TRUTHFULNESS")


if __name__ == "__main__":
    unittest.main()
