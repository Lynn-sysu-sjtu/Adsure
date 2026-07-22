import json
import unittest

from field_mapper import map_feishu_payload
from llm_judgment import apply_context_provenance_guard, build_judgment_messages
from rule_engine import build_context_package, build_judgment_context_package


class ContextProvenanceBoundaryTests(unittest.TestCase):
    def _request(self, background="产品为普通果汁饮品，非保健食品"):
        return map_feishu_payload(
            {
                "record_id": "context-provenance-test",
                "mode": "标准",
                "fields": {
                    "①运营·行业领域": "保健食品",
                    "①运营·物料内容": "治疗肝癌、肺癌",
                    "①运营·补充背景资料": background,
                    "①保健食品·产品品类": "果汁饮品",
                },
            }
        )

    def test_private_judgment_context_adds_background_provenance_and_conflict(self):
        request = self._request()
        public_context = build_context_package(request)
        judgment_context = build_judgment_context_package(request, public_context)

        self.assertNotIn("supplemental_background", public_context)
        self.assertEqual(
            "产品为普通果汁饮品，非保健食品",
            judgment_context["supplemental_background"],
        )
        self.assertEqual(
            "operator_supplied_unverified",
            judgment_context["context_provenance"]["supplemental_background"],
        )
        self.assertEqual(
            "recall_and_routing_label",
            judgment_context["context_provenance"]["industry"],
        )
        self.assertEqual(
            "declared_industry_denied_by_background",
            judgment_context["context_conflicts"][0]["type"],
        )

    def test_context_conflict_requires_explicit_industry_denial(self):
        for background in ("", "产品为普通果汁饮品"):
            request = self._request(background)
            context = build_judgment_context_package(
                request, build_context_package(request)
            )
            self.assertEqual([], context["context_conflicts"])

    def test_prompt_explains_provenance_and_industry_role(self):
        request = self._request()
        context = build_judgment_context_package(request, build_context_package(request))
        messages = build_judgment_messages(context, [], mode="strict")
        payload = json.loads(messages[-1]["content"])
        policy = json.dumps(payload["judgment_policy"], ensure_ascii=False)

        self.assertIn("未经核验", policy)
        self.assertIn("召回与路由", policy)
        self.assertIn("不单独证明产品法律属性", policy)

    def test_guard_downgrades_only_conflicted_industry_specific_confirmations(self):
        request = self._request()
        context = build_judgment_context_package(request, build_context_package(request))
        candidates = [
            {
                "rule_uid": "RUID-GEN-MED",
                "rule_id": "GEN-MED-001",
                "applies_to": {"industries": ["通用"]},
            },
            {
                "rule_uid": "RUID-HF",
                "rule_id": "HF-002",
                "applies_to": {"industries": ["保健食品"]},
            },
        ]
        llm_result = {
            "rule_judgments": [
                {
                    "rule_uid": "RUID-GEN-MED",
                    "rule_id": "GEN-MED-001",
                    "applicability_status": "confirmed_violation",
                    "missing_facts": [],
                    "unsatisfied_elements": [],
                },
                {
                    "rule_uid": "RUID-HF",
                    "rule_id": "HF-002",
                    "applicability_status": "confirmed_violation",
                    "missing_facts": [],
                    "unsatisfied_elements": [],
                },
            ],
            "revision_suggestion": "添加本品不能代替药物声明",
        }

        guarded = apply_context_provenance_guard(llm_result, candidates, context)
        by_id = {item["rule_id"]: item for item in guarded["rule_judgments"]}

        self.assertEqual(
            "confirmed_violation", by_id["GEN-MED-001"]["applicability_status"]
        )
        self.assertEqual(
            "needs_fact_verification", by_id["HF-002"]["applicability_status"]
        )
        self.assertIn(
            "核验产品是否属于保健食品及相应资质",
            by_id["HF-002"]["missing_facts"],
        )
        self.assertNotIn("本品不能代替药物", guarded["revision_suggestion"])

    def test_guard_does_nothing_without_conflict_or_for_not_applicable(self):
        request = self._request("产品为普通果汁饮品")
        context = build_judgment_context_package(request, build_context_package(request))
        original = {
            "rule_judgments": [
                {
                    "rule_uid": "RUID-HF",
                    "rule_id": "HF-002",
                    "applicability_status": "not_applicable",
                }
            ],
            "revision_suggestion": "保持原建议",
        }
        guarded = apply_context_provenance_guard(
            original,
            [
                {
                    "rule_uid": "RUID-HF",
                    "rule_id": "HF-002",
                    "applies_to": {"industries": ["保健食品"]},
                }
            ],
            context,
        )
        self.assertEqual(original, guarded)


if __name__ == "__main__":
    unittest.main()
