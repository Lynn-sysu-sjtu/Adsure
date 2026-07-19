import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rule_vector_index import build_rule_vector_index, load_rule_vector_index
from semantic_recall import semantic_recall_diagnostics, semantic_recall_rules


class FakeEmbeddingClient:
    def __init__(self):
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            if "种草未标广告" in text or "未标广告" in text:
                vectors.append([1.0, 0.0])
            elif "抽奖概率" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.9, 0.1])
        return vectors


class RuleVectorIndexTests(unittest.TestCase):
    def test_build_rule_vector_index_expands_enabled_semantic_scenarios(self):
        rules = [
            {
                "rule_id": "GEN-GOOD-CUSTOMS-001",
                "rule_uid": "RUID-good-customs",
                "title": "广告不得违背社会良好风尚",
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "vector_text": "侮辱物化消费者，以人格贬损方式刺激购买",
                    "semantic_scenarios": [
                        {"scenario_id": "consumer_insult", "vector_text": "使用侮辱性语言贬低消费者人格"},
                        {"scenario_id": "consumer_dehumanization", "vector_text": "把顾客比作狗猪韭菜进行动物化羞辱"},
                        {"scenario_id": "disabled_scenario", "vector_text": "不应进入索引", "enabled": False},
                    ],
                },
            }
        ]
        client = FakeEmbeddingClient()
        with tempfile.TemporaryDirectory() as tmp:
            index = build_rule_vector_index(
                rules,
                output_path=Path(tmp) / "rule_vector_index.json",
                embedding_client=client,
                model="fake-embedding",
            )
        self.assertEqual(2, index["meta"]["vector_count"])
        self.assertEqual(
            ["consumer_insult", "consumer_dehumanization"],
            [item["scenario_id"] for item in index["vectors"]],
        )
        self.assertEqual({"RUID-good-customs"}, {item["rule_uid"] for item in index["vectors"]})
        self.assertEqual(
            ["使用侮辱性语言贬低消费者人格", "把顾客比作狗猪韭菜进行动物化羞辱"],
            client.calls[0],
        )

    def test_build_rule_vector_index_falls_back_to_legacy_parent_vector(self):
        rules = [
            {
                "rule_id": "LEGACY-001",
                "rule_uid": "RUID-legacy",
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "vector_text": "旧版单向量召回文本",
                },
            }
        ]
        client = FakeEmbeddingClient()
        with tempfile.TemporaryDirectory() as tmp:
            index = build_rule_vector_index(
                rules,
                output_path=Path(tmp) / "rule_vector_index.json",
                embedding_client=client,
                model="fake-embedding",
            )
        self.assertEqual(1, index["meta"]["vector_count"])
        self.assertEqual("rule_summary", index["vectors"][0]["scenario_id"])
        self.assertEqual("legacy_vector_text", index["vectors"][0]["vector_source"])
        self.assertEqual("旧版单向量召回文本", index["vectors"][0]["vector_text"])
    def test_build_rule_vector_index_writes_vector_file(self):
        rules = [
            {
                "rule_id": "GEN-IDENT-001",
                "title": "广告应当可识别",
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "种草未标广告，个人心得带购物入口但没有广告标识",
                },
            },
            {
                "rule_id": "NO-SEM-001",
                "recall": {
                    "semantic_enabled": False,
                    "vector_text": "不应进入索引",
                },
            },
        ]
        client = FakeEmbeddingClient()
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "rule_vector_index.json"

            index = build_rule_vector_index(
                rules,
                output_path=output_path,
                embedding_client=client,
                model="fake-embedding",
            )

            self.assertTrue(output_path.exists())
            saved = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual("fake-embedding", saved["meta"]["model"])
            self.assertEqual(1, saved["meta"]["vector_count"])
            self.assertEqual("GEN-IDENT-001", saved["vectors"][0]["rule_id"])
            self.assertEqual([1.0, 0.0], saved["vectors"][0]["embedding"])
            self.assertEqual(saved, index)

    def test_build_rule_vector_index_only_indexes_content_semantic_rules(self):
        rules = [
            {
                "rule_id": "CONTENT-001",
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "fallback",
                    "vector_text": "content violation expression",
                },
            },
            {
                "rule_id": "FACT-001",
                "recall": {
                    "trigger_layer": "fact",
                    "semantic_enabled": True,
                    "semantic_role": "fallback",
                    "vector_text": "fact material proof filing report",
                },
            },
            {
                "rule_id": "WORKFLOW-001",
                "recall": {
                    "trigger_layer": "workflow",
                    "semantic_enabled": True,
                    "semantic_role": "fallback",
                    "vector_text": "platform archive duty process",
                },
            },
            {
                "rule_id": "DISABLED-001",
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "disabled",
                    "vector_text": "disabled semantic rule",
                },
            },
        ]
        client = FakeEmbeddingClient()
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "rule_vector_index.json"

            index = build_rule_vector_index(
                rules,
                output_path=output_path,
                embedding_client=client,
                model="fake-embedding",
            )

        self.assertEqual(["CONTENT-001"], [item["rule_id"] for item in index["vectors"]])
        self.assertEqual([["content violation expression"]], client.calls)
    def test_semantic_recall_uses_cached_rule_vectors(self):
        rules = [
            {
                "rule_id": "GEN-IDENT-001",
                "industry": "通用",
                "applies_to": {"industries": ["通用", "美妆"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "种草未标广告，个人心得带购物入口但没有广告标识",
                },
            }
        ]
        request = {
            "material": {"content": "这像普通分享，但没有标广告"},
            "context": {"industry": "美妆"},
        }
        context_package = {"context_summary": "未标广告", "material_text": request["material"]["content"]}
        client = FakeEmbeddingClient()

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "rule_vector_index.json"
            build_rule_vector_index(rules, output_path=output_path, embedding_client=client, model="fake")
            client.calls.clear()

            recalled = semantic_recall_rules(
                rules,
                request,
                context_package,
                threshold=0.8,
                backend="zhipu",
                embedding_client=client,
                vector_index_path=output_path,
            )

            self.assertEqual(["GEN-IDENT-001"], [rule["rule_id"] for rule, _ in recalled])
            self.assertEqual(1, len(client.calls))
            self.assertEqual(1, len(client.calls[0]))
            self.assertTrue(recalled[0][1][0].startswith("semantic_embedding_cached:"))

    def test_semantic_recall_uses_legacy_cached_parent_until_scenario_index_is_rebuilt(self):
        parent_vector = "种草未标广告，个人心得带购物入口但没有广告标识"
        rules = [
            {
                "rule_id": "GEN-IDENT-001",
                "rule_uid": "RUID-ident",
                "industry": "通用",
                "applies_to": {"industries": ["通用", "美妆"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": parent_vector,
                    "semantic_scenarios": [
                        {"scenario_id": "native_note", "vector_text": "个人种草带购物链接却没有广告标识"},
                        {"scenario_id": "news_style", "vector_text": "新闻报道包装品牌商业推广"},
                    ],
                },
            }
        ]
        request = {
            "material": {"content": "这像普通分享，但没有标广告"},
            "context": {"industry": "美妆"},
        }
        context_package = {"context_summary": "未标广告", "material_text": request["material"]["content"]}
        client = FakeEmbeddingClient()

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "rule_vector_index.json"
            output_path.write_text(
                json.dumps(
                    {
                        "meta": {"model": "fake"},
                        "vectors": [
                            {
                                "rule_id": "GEN-IDENT-001",
                                "vector_text_hash": __import__("rule_vector_index").vector_text_hash(parent_vector),
                                "embedding": [1.0, 0.0],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            recalled = semantic_recall_rules(
                rules,
                request,
                context_package,
                threshold=0.8,
                backend="zhipu",
                embedding_client=client,
                vector_index_path=output_path,
            )

        self.assertEqual(["GEN-IDENT-001"], [rule["rule_id"] for rule, _ in recalled])
        self.assertEqual(1, len(client.calls))
        self.assertEqual(1, len(client.calls[0]))
        self.assertIn("scenario=rule_summary", recalled[0][1][0])
    def test_load_rule_vector_index_returns_empty_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual({}, load_rule_vector_index(Path(tmp) / "missing.json"))

    def test_embedding_threshold_can_be_overridden_by_env(self):
        vector_text = "native style ad without clear disclosure"
        rules = [
            {
                "rule_id": "GEN-IDENT-001",
                "industry": "cosmetics",
                "applies_to": {"industries": ["cosmetics"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": vector_text,
                },
            }
        ]
        request = {
            "material": {"content": "personal note with shopping entry but no ad label"},
            "context": {"industry": "cosmetics"},
        }
        context_package = {"context_summary": "ad disclosure missing", "material_text": request["material"]["content"]}
        client = FakeEmbeddingClient()

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "rule_vector_index.json"
            payload = {
                "meta": {"model": "fake"},
                "vectors": [
                    {
                        "rule_id": "GEN-IDENT-001",
                        "vector_text_hash": __import__("rule_vector_index").vector_text_hash(vector_text),
                        "embedding": [0.6, 0.8],
                    }
                ],
            }
            output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            with patch.dict(os.environ, {"ADSURE_SEMANTIC_THRESHOLD": "0.55"}):
                recalled = semantic_recall_rules(
                    rules,
                    request,
                    context_package,
                    backend="zhipu",
                    embedding_client=client,
                    vector_index_path=output_path,
                )

        self.assertEqual(["GEN-IDENT-001"], [rule["rule_id"] for rule, _ in recalled])

    def test_semantic_recall_diagnostics_reports_scores_and_filter_reasons(self):
        rules = [
            {
                "rule_id": "GEN-IDENT-001",
                "industry": "cosmetics",
                "applies_to": {"industries": ["cosmetics"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "native style ad without clear disclosure",
                },
            },
            {
                "rule_id": "GAME-ONLY-001",
                "industry": "game",
                "applies_to": {"industries": ["game"]},
                "recall": {
                    "semantic_enabled": True,
                    "vector_text": "game lottery probability promise",
                },
            },
        ]
        request = {
            "material": {"content": "personal note with shopping entry but no ad label"},
            "context": {"industry": "cosmetics"},
        }
        context_package = {"context_summary": "ad disclosure missing", "material_text": request["material"]["content"]}
        client = FakeEmbeddingClient()

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "rule_vector_index.json"
            build_rule_vector_index(rules, output_path=output_path, embedding_client=client, model="fake")
            client.calls.clear()

            diagnostics = semantic_recall_diagnostics(
                rules,
                request,
                context_package,
                threshold=0.8,
                backend="zhipu",
                embedding_client=client,
                vector_index_path=output_path,
                top_k=10,
            )

        self.assertEqual("zhipu", diagnostics["backend"])
        self.assertEqual(0.8, diagnostics["threshold"])
        self.assertEqual("GEN-IDENT-001", diagnostics["top_candidates"][0]["rule_id"])
        self.assertGreaterEqual(diagnostics["top_candidates"][0]["score"], 0.8)
        rejected = {item["rule_id"]: item for item in diagnostics["rejected_rules"]}
        self.assertIn("GAME-ONLY-001", rejected)
        self.assertIn("industry_scope_mismatch", rejected["GAME-ONLY-001"]["reasons"])


if __name__ == "__main__":
    unittest.main()

