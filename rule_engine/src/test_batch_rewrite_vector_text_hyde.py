import unittest

from batch_rewrite_vector_text_hyde import _already_reviewed, _clip_vector_text, _should_process_rule


class HydeRuleFilterTests(unittest.TestCase):
    def test_processes_only_content_semantic_enabled_rules(self):
        self.assertTrue(
            _should_process_rule(
                {
                    "recall": {
                        "trigger_layer": "content",
                        "semantic_enabled": True,
                        "semantic_role": "fallback",
                    }
                }
            )
        )

    def test_skips_fact_workflow_disabled_and_semantic_off(self):
        cases = [
            {"recall": {"trigger_layer": "fact", "semantic_enabled": True, "semantic_role": "fallback"}},
            {"recall": {"trigger_layer": "workflow", "semantic_enabled": True, "semantic_role": "primary"}},
            {"recall": {"trigger_layer": "content", "semantic_enabled": False, "semantic_role": "fallback"}},
            {"recall": {"trigger_layer": "content", "semantic_enabled": True, "semantic_role": "disabled"}},
        ]

        for rule in cases:
            with self.subTest(rule=rule):
                self.assertFalse(_should_process_rule(rule))

    def test_already_reviewed_returns_false_when_vector_text_is_too_long(self):
        rule = {
            "recall": {
                "vector_text": "x" * 80,
                "hyde_review": {"prompt_version": "hyde_vector_text_rewrite_v1_20260714"},
            }
        }

        self.assertFalse(_already_reviewed(rule, overwrite=False))
    def test_vector_text_is_clipped_to_50_characters(self):
        text = "x" * 80

        self.assertEqual(50, len(_clip_vector_text(text)))
    def test_missing_trigger_layer_defaults_to_content_for_backward_compatibility(self):
        self.assertTrue(
            _should_process_rule(
                {"recall": {"semantic_enabled": True, "semantic_role": "primary"}}
            )
        )


if __name__ == "__main__":
    unittest.main()


