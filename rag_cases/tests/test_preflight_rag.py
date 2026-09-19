import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.preflight_rag import check_production_readiness
from src.semantic_index import chunks_fingerprint


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
        return chunk

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

    def test_semantic_can_be_optional_or_required(self):
        self.write_valid_catalog()

        optional_summary, optional_errors = check_production_readiness(
            self.data_dir,
            "production",
            "test-secret",
            retrieval_mode="hybrid",
            require_semantic=False,
        )
        self.assertEqual(optional_errors, [])
        self.assertEqual(optional_summary["effective_retrieval_mode"], "lexical")
        self.assertEqual(optional_summary["semantic_status"], "missing_index")

        _required_summary, required_errors = check_production_readiness(
            self.data_dir,
            "production",
            "test-secret",
            retrieval_mode="hybrid",
            require_semantic=True,
        )
        self.assertTrue(
            any(error.startswith("语义检索未就绪") for error in required_errors)
        )

    def write_semantic_index(
        self,
        chunk,
        *,
        model: str = "embedding-3",
        dimension: int = 2048,
    ):
        payload = {
            "index_type": "dense_sentence_embedding",
            "model_name": model,
            "dimension": dimension,
            "normalized": True,
            "chunk_fingerprint": chunks_fingerprint([chunk]),
            "document_count": 1,
            "documents": [
                {
                    "chunk_id": chunk["chunk_id"],
                    "case_id": chunk["case_id"],
                    "embedding": [0.0] * dimension,
                }
            ],
        }
        (self.data_dir / "chunks/production_semantic_index.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def zhipu_kwargs(self, **overrides):
        kwargs = {
            "retrieval_mode": "hybrid",
            "require_semantic": True,
            "embedding_provider": "zhipu",
            "embedding_model": "embedding-3",
            "embedding_dimensions": 2048,
            "embedding_api_key": "test-zhipu-key",
        }
        kwargs.update(overrides)
        return kwargs

    def test_zhipu_without_api_key_fails(self):
        chunk = self.write_valid_catalog()
        self.write_semantic_index(chunk)

        _summary, errors = check_production_readiness(
            self.data_dir,
            "production",
            "test-secret",
            **self.zhipu_kwargs(embedding_api_key=""),
        )

        self.assertTrue(
            any("ZHIPU_API_KEY" in error for error in errors),
            errors,
        )

    def test_zhipu_index_model_mismatch_fails(self):
        chunk = self.write_valid_catalog()
        self.write_semantic_index(chunk, model="BAAI/bge-base-zh-v1.5")

        _summary, errors = check_production_readiness(
            self.data_dir,
            "production",
            "test-secret",
            **self.zhipu_kwargs(),
        )

        self.assertTrue(
            any("语义索引模型不匹配" in error for error in errors),
            errors,
        )

    def test_zhipu_index_dimension_mismatch_fails(self):
        chunk = self.write_valid_catalog()
        self.write_semantic_index(chunk, dimension=768)

        _summary, errors = check_production_readiness(
            self.data_dir,
            "production",
            "test-secret",
            **self.zhipu_kwargs(),
        )

        self.assertTrue(
            any("语义索引维度不匹配" in error for error in errors),
            errors,
        )

    def test_zhipu_index_matching_embedding_3_passes(self):
        chunk = self.write_valid_catalog()
        self.write_semantic_index(chunk)

        encoder = lambda texts: [[0.0] * 2048 for _ in texts]  # noqa: E731
        with mock.patch("src.semantic_index.configured_encoder", return_value=encoder):
            summary, errors = check_production_readiness(
                self.data_dir,
                "production",
                "test-secret",
                **self.zhipu_kwargs(),
            )

        self.assertEqual(errors, [])
        self.assertEqual(summary["embedding_provider"], "zhipu")
        self.assertEqual(summary["embedding_model"], "embedding-3")
        self.assertEqual(summary["embedding_dimension"], 2048)
        self.assertEqual(summary["semantic_index_model"], "embedding-3")
        self.assertEqual(summary["semantic_index_dimension"], 2048)
        self.assertEqual(summary["semantic_status"], "ready")
        self.assertEqual(summary["effective_retrieval_mode"], "hybrid")

    def test_zhipu_api_failure_fails_instead_of_silent_lexical(self):
        chunk = self.write_valid_catalog()
        self.write_semantic_index(chunk)

        def broken_encoder(texts):
            raise RuntimeError("zhipu api unavailable")

        with mock.patch(
            "src.semantic_index.configured_encoder",
            return_value=broken_encoder,
        ):
            summary, errors = check_production_readiness(
                self.data_dir,
                "production",
                "test-secret",
                **self.zhipu_kwargs(),
            )

        self.assertTrue(
            any(error.startswith("语义检索未就绪") for error in errors),
            errors,
        )
        self.assertTrue(summary["semantic_status"].startswith("model_error"))
        self.assertNotEqual(summary["semantic_status"], "ready")


if __name__ == "__main__":
    unittest.main()
