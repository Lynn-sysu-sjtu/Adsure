import json
import tempfile
import unittest
from pathlib import Path

from src.export_rule_mapping_queue import run


class RuleMappingQueueTests(unittest.TestCase):
    def test_exports_only_unmapped_production_cases_without_guessing_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structured = root / "structured"
            structured.mkdir()
            base_case = {
                "title": "某违法广告案",
                "source_type": "official_typical_case",
                "source_name": "市场监管部门",
                "source_url": "https://example.gov.cn/case",
                "publish_date": "2026-01-01",
                "source_verification_status": "source_verified",
                "raw_text_path": "data/raw_text/source.json",
                "penalty_authority": "某地市场监督管理局",
                "party_name": "某公司",
                "industry": "食品",
                "violation_type": "疾病治疗功效宣传",
                "product_or_service": "普通食品",
                "risk_dimensions": ["疾病治疗功效宣传"],
                "illegal_claims": ["宣称可以治疗疾病"],
                "facts_summary": "当事人发布普通食品可以治疗疾病的广告。",
                "legal_basis": ["《中华人民共和国广告法》有关规定"],
                "penalty_result": "依法处罚",
                "regulatory_logic": "普通食品不得宣传疾病治疗功效。",
                "vector_text": "经营者发布普通食品具有疾病治疗功效的广告并被监管部门依法处罚。",
                "review_status": "approved",
                "approved_for_rag": True,
                "scope": "public",
            }
            unmapped = {"case_id": "case_unmapped", "mapped_rule_ids": [], **base_case}
            mapped = {"case_id": "case_mapped", "mapped_rule_ids": ["RULE-001"], **base_case}
            candidate = {
                "case_id": "case_candidate",
                "mapped_rule_ids": [],
                **base_case,
                "source_type": "manual_compilation_pending_source_verification",
                "source_verification_status": "pending_source_lookup",
                "review_status": "pending_review",
                "approved_for_rag": False,
            }
            for case in (unmapped, mapped, candidate):
                (structured / f"{case['case_id']}.json").write_text(
                    json.dumps(case, ensure_ascii=False),
                    encoding="utf-8",
                )

            json_output = root / "queue.json"
            markdown_output = root / "queue.md"
            queue = run(structured, json_output, markdown_output)

            self.assertEqual([item["case_id"] for item in queue], ["case_unmapped"])
            self.assertEqual(queue[0]["mapped_rule_ids"], [])
            self.assertEqual(queue[0]["mapping_status"], "pending_rule_owner_review")
            self.assertEqual(
                json.loads(json_output.read_text(encoding="utf-8")),
                queue,
            )
            markdown = markdown_output.read_text(encoding="utf-8")
            self.assertIn("不自动推断规则 ID 或具体法条", markdown)
            self.assertNotIn("RULE-001", markdown)


if __name__ == "__main__":
    unittest.main()
