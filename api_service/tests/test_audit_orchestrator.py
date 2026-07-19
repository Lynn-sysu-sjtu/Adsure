import unittest

from api_service.services.audit_orchestrator import AuditOrchestrator


AUDIT_REQUEST = {
    "tenant_id": "adsure_demo",
    "request_id": "rec_demo_001",
    "source": "feishu",
    "material": {"content": "充3元送一只狗"},
    "context": {"industry": "游戏"},
}


class FakeRuleEngineClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def audit(self, payload):
        self.requests.append(payload)
        return self.response


class FakeRagClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def search(self, payload):
        self.requests.append(payload)
        if self.error:
            raise self.error
        return self.response


class AuditOrchestratorTests(unittest.TestCase):
    def test_merges_related_cases_into_successful_rule_engine_result(self):
        rule_response = {
            "code": 0,
            "msg": "ok",
            "data": {
                "tenant_id": "adsure_demo",
                "request_id": "rec_demo_001",
                "routing": "运营",
                "matched_rules": [
                    {"rule_id": "GAME-AD-002", "dimension": "虚假宣传"}
                ],
            },
        }
        rag_response = {
            "code": 0,
            "msg": "ok",
            "data": {
                "cases": [
                    {
                        "case_id": "case_001",
                        "title": "赠送活动未兑现案例",
                        "summary": "广告承诺赠品但未实际提供",
                        "source": "公开监管案例",
                        "similarity": 0.82,
                    }
                ]
            },
        }
        rule_client = FakeRuleEngineClient(rule_response)
        rag_client = FakeRagClient(response=rag_response)

        result = AuditOrchestrator(rule_client, rag_client).audit(AUDIT_REQUEST)

        self.assertEqual(0, result["code"])
        self.assertEqual("ok", result["data"]["case_search_status"])
        self.assertEqual("case_001", result["data"]["related_cases"][0]["case_id"])
        self.assertEqual(
            {
                "tenant_id": "adsure_demo",
                "query": "充3元送一只狗",
                "industry": "游戏",
                "matched_rules": [
                    {"rule_id": "GAME-AD-002", "dimension": "虚假宣传"}
                ],
                "top_k": 3,
            },
            rag_client.requests[0],
        )

    def test_rag_exception_degrades_to_empty_cases_without_failing_audit(self):
        rule_response = {
            "code": 0,
            "msg": "ok",
            "data": {"routing": "法务", "matched_rules": []},
        }
        rag_client = FakeRagClient(error=TimeoutError("rag timeout"))

        result = AuditOrchestrator(FakeRuleEngineClient(rule_response), rag_client).audit(AUDIT_REQUEST)

        self.assertEqual(0, result["code"])
        self.assertEqual([], result["data"]["related_cases"])
        self.assertEqual("unavailable", result["data"]["case_search_status"])

    def test_rule_engine_failure_is_returned_without_calling_rag(self):
        rule_response = {"code": -1, "msg": "缺少必填字段", "data": None}
        rag_client = FakeRagClient(response={"code": 0, "data": {"cases": []}})

        result = AuditOrchestrator(FakeRuleEngineClient(rule_response), rag_client).audit(AUDIT_REQUEST)

        self.assertEqual(rule_response, result)
        self.assertEqual([], rag_client.requests)


if __name__ == "__main__":
    unittest.main()
