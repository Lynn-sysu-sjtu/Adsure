import os
import threading
import unittest
from unittest.mock import patch

from rule_engine import recall_rules


def _rule(rule_id, term=None):
    return {
        "rule_id": rule_id,
        "serial_no": 1,
        "risk_level": "中",
        "applies_to": {"industries": ["通用"]},
        "detection": {"keyword_signals": {"hit_terms": [term] if term else []}},
        "recall": {"trigger_layer": "content", "semantic_role": "primary"},
    }


class ThreeWayRecallOrchestrationTests(unittest.TestCase):
    def test_semantic_and_catalog_branches_run_in_parallel_and_merge(self):
        keyword_rule = _rule("KEYWORD-001", "命中词")
        semantic_rule = _rule("SEMANTIC-001")
        catalog_rule = _rule("CATALOG-001")
        barrier = threading.Barrier(2, timeout=1)

        def fake_semantic(*args, **kwargs):
            barrier.wait()
            return [(semantic_rule, ["semantic_embedding:0.800:scenario=test"])]

        def fake_catalog(*args, **kwargs):
            barrier.wait()
            return [(catalog_rule, ["llm_catalog:开放性风险"])]

        request = {
            "material": {"content": "命中词"},
            "context": {"industry": "通用", "platforms": [], "core_claims": []},
        }
        context_package = {"material_text": "命中词", "industry": "通用"}

        with patch.dict(os.environ, {"ADSURE_CATALOG_RECALL_ENABLED": "true"}, clear=False):
            with patch("rule_engine.semantic_recall_rules", side_effect=fake_semantic):
                with patch("rule_engine.catalog_recall_rules", side_effect=fake_catalog):
                    recalled = recall_rules(
                        [keyword_rule, semantic_rule, catalog_rule],
                        request,
                        context_package=context_package,
                    )

        self.assertEqual(
            {"KEYWORD-001", "SEMANTIC-001", "CATALOG-001"},
            {rule["rule_id"] for rule, _ in recalled},
        )

    def test_catalog_exception_does_not_break_keyword_and_semantic_recall(self):
        keyword_rule = _rule("KEYWORD-001", "命中词")
        semantic_rule = _rule("SEMANTIC-001")
        request = {
            "material": {"content": "命中词"},
            "context": {"industry": "通用", "platforms": [], "core_claims": []},
        }

        with patch.dict(os.environ, {"ADSURE_CATALOG_RECALL_ENABLED": "true"}, clear=False):
            with patch(
                "rule_engine.semantic_recall_rules",
                return_value=[(semantic_rule, ["semantic_embedding:0.800:scenario=test"])],
            ):
                with patch("rule_engine.catalog_recall_rules", side_effect=RuntimeError("boom")):
                    recalled = recall_rules(
                        [keyword_rule, semantic_rule],
                        request,
                        context_package={"material_text": "命中词", "industry": "通用"},
                    )

        self.assertEqual(
            {"KEYWORD-001", "SEMANTIC-001"},
            {rule["rule_id"] for rule, _ in recalled},
        )

    def test_same_parent_from_semantic_and_catalog_is_returned_once(self):
        shared_rule = _rule("OPEN-001")
        request = {
            "material": {"content": "普通文案"},
            "context": {"industry": "通用", "platforms": [], "core_claims": []},
        }

        with patch.dict(os.environ, {"ADSURE_CATALOG_RECALL_ENABLED": "true"}, clear=False):
            with patch(
                "rule_engine.semantic_recall_rules",
                return_value=[(shared_rule, ["semantic_embedding:0.800:scenario=test"])],
            ):
                with patch(
                    "rule_engine.catalog_recall_rules",
                    return_value=[(shared_rule, ["llm_catalog:开放性风险"])],
                ):
                    recalled = recall_rules(
                        [shared_rule],
                        request,
                        context_package={"material_text": "普通文案", "industry": "通用"},
                    )

        self.assertEqual(1, len(recalled))
        self.assertEqual(2, len(recalled[0][1]))


if __name__ == "__main__":
    unittest.main()
