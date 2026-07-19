import json
import tempfile
import unittest
from pathlib import Path

from src.preflight_rag import check_production_readiness


class RagPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "data"
        (self.data_dir / "chunks").mkdir(parents=True)
        (self.data_dir / "structured").mkdir()
        (self.data_dir / "raw_text").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_valid_catalog(self):
        case = {
            "case_id": "official_case_001",
            "title": "某地市场监管局查处违法广告案",
            "source_type": "official_typical_case",
            "source_name": "市场监管部门",
            "source_url": "https://example.gov.cn/case",
            "publish_date": "2026-01-01",
            "source_verification_status": "source_verified",
            "raw_text_path": "data/raw_text/official_case_001.json",
            "penalty_authority": "某地市场监督管理局",
            "party_name": "某公司",
            "industry": "食品",
            "violation_type": "普通食品疾病治疗功效宣传",
            "product_or_service": "普通食品",
            "ad_channel": "互联网广告",
            "risk_dimensions": ["疾病治疗功效宣传"],
            "illegal_claims": ["宣称普通食品可以治疗疾病"],
            "facts_summary": "当事人发布普通食品具有疾病治疗功效的广告。",
            "legal_basis": ["《中华人民共和国广告法》有关规定"],
            "penalty_result": "依法处罚",
            "regulatory_logic": "普通食品不得宣传疾病治疗功效。",
            "vector_text": "经营者发布普通食品具有疾病治疗功效的互联网广告并被依法处罚。",
            "review_status": "approved",
            "approved_for_rag": True,
            "scope": "public",
        }
        chunk = {
            "chunk_id": "official_case_001__case_summary",
            "case_id": case["case_id"],
            "chunk_type": "case_summary",
            "scope": "public",
            "title": case["title"],
            "source_name": case["source_name"],
            "source_url": case["source_url"],
            "risk_dimensions": case["risk_dimensions"],
            "keywords": [],
            "text": case["vector_text"],
            "metadata": {
                "source_type": case["source_type"],
                "industry": case["industry"],
                "scope": "public",
            },
        }
        (self.data_dir / "structured/official_case_001.json").write_text(
            json.dumps(case, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.data_dir / "raw_text/official_case_001.json").write_text(
            json.dumps({"text": case["facts_summary"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.data_dir / "chunks/production_chunks.json").write_text(
            json.dumps([chunk], ensure_ascii=False),
            encoding="utf-8",
        )

    def test_valid_production_catalog_passes(self):
        self.write_valid_catalog()

        summary, errors = check_production_readiness(
            self.data_dir,
            "production",
            "test-secret",
        )

        self.assertEqual(errors, [])
        self.assertEqual(summary["case_count"], 1)
        self.assertEqual(summary["public_case_count"], 1)
        self.assertEqual(summary["chunk_count"], 1)
        self.assertRegex(summary["index_version"], r"^[0-9a-f]{16}$")

    def test_missing_key_and_empty_index_fail(self):
        (self.data_dir / "chunks/production_chunks.json").write_text(
            "[]",
            encoding="utf-8",
        )

        _summary, errors = check_production_readiness(
            self.data_dir,
            "production",
            "",
        )

        self.assertIn("ADSURE_API_KEY 未配置", errors)
        self.assertIn("正式索引为空", errors)

    def test_candidate_scope_and_missing_raw_text_fail(self):
        self.write_valid_catalog()
        (self.data_dir / "raw_text/official_case_001.json").unlink()

        _summary, errors = check_production_readiness(
            self.data_dir,
            "candidate",
            "test-secret",
        )

        self.assertIn("CASE_ENGINE_INDEX_SCOPE 必须为 production", errors)
        self.assertIn("正式索引为空", errors)

    def test_missing_raw_text_fails(self):
        self.write_valid_catalog()
        (self.data_dir / "raw_text/official_case_001.json").unlink()

        _summary, errors = check_production_readiness(
            self.data_dir,
            "production",
            "test-secret",
        )

        self.assertTrue(any(error.startswith("案例原文不存在") for error in errors))


if __name__ == "__main__":
    unittest.main()
