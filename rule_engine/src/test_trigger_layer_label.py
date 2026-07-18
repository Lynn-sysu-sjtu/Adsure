import unittest

from batch_label_trigger_layer import classify_rule_heuristic


class TriggerLayerHeuristicTests(unittest.TestCase):
    def test_classifies_content_rule_from_ad_copy_signals(self):
        rule = {
            "rule_id": "GEN-ABS-001",
            "title": "\u5e7f\u544a\u4e0d\u5f97\u4f7f\u7528\u7edd\u5bf9\u5316\u7528\u8bed",
            "dimension": "\u7edd\u5bf9\u5316\u7528\u8bed",
            "detection": {
                "keyword_signals": {
                    "hit_terms": ["\u6700", "\u6700\u4f73", "\u7b2c\u4e00", "\u9876\u7ea7"],
                    "regex": ["(\u56fd\u5bb6\u7ea7|\u6700\u9ad8\u7ea7|\u6700\u4f73)"],
                }
            },
            "recall": {"vector_text": "\u5168\u7f51\u7b2c\u4e00\u6700\u597d\u6700\u4f73\u9876\u7ea7\u6548\u679c"},
        }

        result = classify_rule_heuristic(rule)

        self.assertEqual("content", result["trigger_layer"])
        self.assertEqual("high", result["confidence"])
        self.assertEqual("heuristic", result["source"])

    def test_classifies_fact_rule_from_qualification_signals(self):
        rule = {
            "rule_id": "COSM-FILING-001",
            "title": "\u7279\u6b8a\u5316\u5986\u54c1\u5e7f\u544a\u5e94\u6838\u9a8c\u6ce8\u518c\u5907\u6848\u4fe1\u606f",
            "dimension": "\u5907\u6848\u8d44\u8d28\u6838\u9a8c",
            "preconditions": {
                "required_context_fields": ["product_category", "filing_number"]
            },
            "legal_basis": [
                {"text": "\u6d89\u53ca\u7279\u6b8a\u5316\u5986\u54c1\u6ce8\u518c\u8bc1\u3001\u5907\u6848\u53f7\u3001\u6279\u51c6\u6587\u53f7\u3001\u68c0\u9a8c\u62a5\u544a\u7b49\u6750\u6599\u3002"}
            ],
            "recall": {"semantic_reason": "\u4f9d\u8d56\u5907\u6848\u53f7\u548c\u8bc1\u660e\u6750\u6599\u6838\u9a8c"},
        }

        result = classify_rule_heuristic(rule)

        self.assertEqual("fact", result["trigger_layer"])
        self.assertEqual("high", result["confidence"])
        self.assertEqual("heuristic", result["source"])

    def test_classifies_workflow_rule_from_platform_obligation_signals(self):
        rule = {
            "rule_id": "PLAT-ARCHIVE-001",
            "title": "\u5e7f\u544a\u7ecf\u8425\u8005\u548c\u5e7f\u544a\u53d1\u5e03\u8005\u5e94\u5efa\u7acb\u5e7f\u544a\u6863\u6848\u4fdd\u5b58\u5236\u5ea6",
            "dimension": "\u5e73\u53f0\u8d23\u4efb\u4e0e\u6863\u6848\u6d41\u7a0b",
            "legal_basis": [
                {"text": "\u5e7f\u544a\u7ecf\u8425\u8005\u3001\u5e7f\u544a\u53d1\u5e03\u8005\u5e94\u5f53\u67e5\u9a8c\u6709\u5173\u8bc1\u660e\u6587\u4ef6\uff0c\u6838\u5bf9\u5e7f\u544a\u5185\u5bb9\uff0c\u5efa\u7acb\u5e7f\u544a\u6863\u6848\u5e76\u4fdd\u5b58\u3002"}
            ],
            "routing": {"default_route": "legal_review_required"},
        }

        result = classify_rule_heuristic(rule)

        self.assertEqual("workflow", result["trigger_layer"])
        self.assertEqual("high", result["confidence"])
        self.assertEqual("heuristic", result["source"])

    def test_does_not_treat_generic_delete_hint_as_workflow(self):
        rule = {
            "rule_id": "HF-AL-002",
            "title": "\u9152\u7c7b\u5e7f\u544a\u4e0d\u5f97\u51fa\u73b0\u996e\u9152\u7684\u52a8\u4f5c",
            "dimension": "\u9152\u7c7b\u5e7f\u544a\u5185\u5bb9\u9650\u5236",
            "legal_attention": {
                "route_reason": "\u8fd0\u8425\u53ef\u76f4\u63a5\u5220\u9664\u996e\u9152\u52a8\u4f5c\u76f8\u5173\u8868\u8ff0\u6216\u753b\u9762\u3002"
            },
            "detection": {
                "keyword_signals": {
                    "hit_terms": ["\u996e\u9152", "\u9152\u7c7b\u5e7f\u544a", "\u9a7e\u9a76"]
                }
            },
        }

        result = classify_rule_heuristic(rule)

        self.assertEqual("content", result["trigger_layer"])


if __name__ == "__main__":
    unittest.main()
