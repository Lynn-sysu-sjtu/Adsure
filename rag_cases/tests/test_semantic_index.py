import unittest

from src.api import best_chunks_by_case
from src.semantic_index import SemanticIndex, build_index


class SemanticIndexTests(unittest.TestCase):
    def test_build_and_query_with_injected_encoder(self):
        chunks = [
            {
                "chunk_id": "food__case_summary",
                "case_id": "food",
                "text": "普通食品宣称治疗高血压",
            },
            {
                "chunk_id": "real_estate__case_summary",
                "case_id": "real_estate",
                "text": "房地产广告承诺升值",
            },
        ]
        vectors = {
            "普通食品宣称治疗高血压": [1.0, 0.0],
            "房地产广告承诺升值": [0.0, 1.0],
            "食品能够治病": [0.9, 0.1],
        }

        def encoder(texts):
            return [vectors[text] for text in texts]

        payload = build_index(
            chunks,
            model_name="test-model",
            encoder=encoder,
        )
        index = SemanticIndex(payload, encoder=encoder)
        scores = index.scores(
            "食品能够治病",
            {"food__case_summary", "real_estate__case_summary"},
        )

        self.assertEqual(payload["dimension"], 2)
        self.assertEqual(scores[0].chunk_id, "food__case_summary")
        self.assertGreater(scores[0].score, scores[1].score)

    def test_invalid_vector_dimension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "维度"):
            SemanticIndex(
                {
                    "index_type": "dense_sentence_embedding",
                    "model_name": "test-model",
                    "dimension": 2,
                    "document_count": 1,
                    "documents": [
                        {"chunk_id": "broken", "embedding": [1.0]}
                    ],
                }
            )

    def test_declared_document_count_must_match_documents(self):
        with self.assertRaisesRegex(ValueError, "文档数量"):
            SemanticIndex(
                {
                    "index_type": "dense_sentence_embedding",
                    "model_name": "test",
                    "dimension": 2,
                    "document_count": 2,
                    "chunk_fingerprint": "test",
                    "documents": [
                        {"chunk_id": "only-one", "embedding": [1.0, 0.0]}
                    ],
                }
            )

    def test_hybrid_fusion_can_recall_semantic_only_paraphrase(self):
        chunks = [
            {
                "chunk_id": "medicine__case_summary",
                "case_id": "medicine",
                "text": "企业以健康科普形式发布处方药广告",
            }
        ]

        def encoder(texts):
            vectors = {
                "企业以健康科普形式发布处方药广告": [1.0, 0.0],
                "用养生文章向大众推广只能凭处方购买的药物": [1.0, 0.0],
            }
            return [vectors[text] for text in texts]

        payload = build_index(
            chunks,
            model_name="test-model",
            encoder=encoder,
        )
        index = SemanticIndex(payload, encoder=encoder)
        results = best_chunks_by_case(
            "用养生文章向大众推广只能凭处方购买的药物",
            chunks,
            top_k=3,
            semantic_index=index,
            retrieval_mode="hybrid",
            min_semantic_score=0.6,
        )

        self.assertEqual(results[0][1]["case_id"], "medicine")
        self.assertEqual(results[0][2]["score_type"], "hybrid_rrf")
        self.assertEqual(results[0][2]["matched_terms"], [])
        self.assertAlmostEqual(results[0][2]["semantic_similarity"], 1.0)


if __name__ == "__main__":
    unittest.main()
