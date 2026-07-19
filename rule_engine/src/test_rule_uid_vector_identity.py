# -*- coding: utf-8 -*-
"""Regression tests for UID-based vector and parent identity."""

import tempfile
import unittest
from pathlib import Path

from rule_vector_index import build_rule_vector_index, load_rule_vector_index, vector_text_hash
from semantic_recall import semantic_recall_rules


class IdentityEmbeddingClient:
    model = "identity-test"

    def embed_texts(self, texts):
        vectors = []
        for text in texts:
            vectors.append([0.0, 1.0] if "second" in text else [1.0, 0.0])
        return vectors


class RuleUidVectorIdentityTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {
                "rule_uid": "RUID-first",
                "rule_id": "DUP-001",
                "title": "first rule",
                "applies_to": {"industries": ["通用"]},
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "primary",
                    "vector_text": "first semantic scene",
                },
            },
            {
                "rule_uid": "RUID-second",
                "rule_id": "DUP-001",
                "title": "second rule",
                "applies_to": {"industries": ["通用"]},
                "recall": {
                    "trigger_layer": "content",
                    "semantic_enabled": True,
                    "semantic_role": "primary",
                    "vector_text": "second semantic scene",
                },
            },
        ]

    def test_loaded_index_keys_use_rule_uid_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "index.json"
            build_rule_vector_index(
                self.rules,
                output_path=path,
                embedding_client=IdentityEmbeddingClient(),
            )
            entries = load_rule_vector_index(path)

        self.assertIn(("RUID-first", "rule_summary", vector_text_hash("first semantic scene")), entries)
        self.assertIn(("RUID-second", "rule_summary", vector_text_hash("second semantic scene")), entries)

    def test_semantic_recall_does_not_merge_distinct_uids_with_same_legacy_id(self):
        request = {
            "material": {"content": "second"},
            "context": {"industry": "通用"},
        }
        context = {"material_text": "second", "context_summary": "second"}
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "index.json"
            client = IdentityEmbeddingClient()
            build_rule_vector_index(self.rules, output_path=path, embedding_client=client)
            recalled = semantic_recall_rules(
                self.rules,
                request,
                context,
                threshold=0.9,
                backend="zhipu",
                embedding_client=client,
                vector_index_path=path,
            )

        self.assertEqual(["RUID-second"], [rule["rule_uid"] for rule, _ in recalled])


if __name__ == "__main__":
    unittest.main()
