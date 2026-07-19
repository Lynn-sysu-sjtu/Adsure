# -*- coding: utf-8 -*-
"""Tests for offline semantic legal-issue candidate generation."""

import json
import tempfile
import unittest
from pathlib import Path

from build_legal_issue_groups import build_candidate_report, candidate_pairs


class SemanticRuleClusteringTests(unittest.TestCase):
    def setUp(self):
        self.rules = [
            {
                "rule_uid": "RUID-CONTENT-1",
                "rule_id": "CONTENT-1",
                "title": "普通化妆品不得宣称美白",
                "industry": "美妆",
                "recall": {"trigger_layer": "content"},
            },
            {
                "rule_uid": "RUID-CONTENT-2",
                "rule_id": "CONTENT-2",
                "title": "非特殊化妆品不得宣传特殊功效",
                "industry": "美妆",
                "recall": {"trigger_layer": "content"},
            },
            {
                "rule_uid": "RUID-FACT",
                "rule_id": "FACT-1",
                "title": "核验产品备案",
                "industry": "美妆",
                "recall": {"trigger_layer": "fact"},
            },
            {
                "rule_uid": "RUID-GAME",
                "rule_id": "GAME-1",
                "title": "游戏抽奖规则",
                "industry": "游戏",
                "recall": {"trigger_layer": "content"},
            },
        ]
        self.embeddings = {
            "RUID-CONTENT-1": [[1.0, 0.0]],
            "RUID-CONTENT-2": [[0.99, 0.01]],
            "RUID-FACT": [[1.0, 0.0]],
            "RUID-GAME": [[1.0, 0.0]],
        }

    def test_candidates_respect_trigger_layer_and_industry(self):
        pairs = candidate_pairs(self.rules, self.embeddings, threshold=0.95)

        self.assertEqual(
            [("RUID-CONTENT-1", "RUID-CONTENT-2")],
            [(item["left_uid"], item["right_uid"]) for item in pairs],
        )

    def test_uses_best_scenario_similarity_and_stable_order(self):
        embeddings = dict(self.embeddings)
        embeddings["RUID-CONTENT-1"] = [[0.0, 1.0], [1.0, 0.0]]
        pairs = candidate_pairs(self.rules[:2], embeddings, threshold=0.95)

        self.assertEqual(1, len(pairs))
        self.assertGreater(pairs[0]["similarity"], 0.99)

    def test_report_write_does_not_modify_approved_group_asset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "candidates.json"
            approved = Path(temp_dir) / "legal_issue_groups.json"
            approved.write_text('{"groups": []}', encoding="utf-8")
            before = approved.read_text(encoding="utf-8")

            report = build_candidate_report(
                self.rules,
                self.embeddings,
                threshold=0.95,
                output_path=output,
            )

            self.assertTrue(output.exists())
            self.assertEqual(before, approved.read_text(encoding="utf-8"))
            self.assertEqual(report, json.loads(output.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
