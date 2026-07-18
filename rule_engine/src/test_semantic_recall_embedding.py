import unittest

from semantic_recall import semantic_recall_rules


class FakeEmbeddingClient:
    def embed_texts(self, texts):
        vectors = []
        for text in texts:
            if "导流未标广告" in text:
                vectors.append([1.0, 0.0, 0.0])
            elif "抽奖概率" in text:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.95, 0.05, 0.0])
        return vectors


class SemanticRecallEmbeddingTests(unittest.TestCase):
    def test_embedding_backend_uses_vector_similarity(self):
        request = {
            "material": {"content": "像普通分享一样引导下单，但是没有标广告"},
            "context": {
                "industry": "美妆",
                "material_type": "图文文案",
                "product_category": "护肤",
                "channels": ["社交平台"],
            },
        }
        context_package = {"context_summary": "导流未标广告", "material_text": request["material"]["content"]}
        rules = [
            {
                "rule_id": "GEN-IDENT-001",
                "industry": "通用",
                "applies_to": {"industries": ["通用", "美妆"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "导流未标广告，种草分享带购物链接但没有显著标明广告",
                },
            },
            {
                "rule_id": "GAME-PROB-001",
                "industry": "游戏",
                "applies_to": {"industries": ["游戏"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "抽奖概率与实际掉率不一致",
                },
            },
        ]

        recalled = semantic_recall_rules(
            rules,
            request,
            context_package,
            threshold=0.8,
            limit=5,
            backend="embedding",
            embedding_client=FakeEmbeddingClient(),
        )

        self.assertEqual(["GEN-IDENT-001"], [rule["rule_id"] for rule, _ in recalled])
        self.assertTrue(recalled[0][1][0].startswith("semantic_embedding:"))


if __name__ == "__main__":
    unittest.main()
