import unittest

from api_service.app import audit_endpoint, health_endpoint
from api_service.clients.rag_client import MockRagClient


class FakeOrchestrator:
    def __init__(self):
        self.requests = []

    def audit(self, payload):
        self.requests.append(payload)
        return {"code": 0, "msg": "ok", "data": {"related_cases": []}}


class ApiServiceAppTests(unittest.TestCase):
    def test_health_endpoint_is_dependency_free(self):
        self.assertEqual(
            {"status": "ok", "service": "adsure-api-service", "version": "0.1.0"},
            health_endpoint(),
        )

    def test_audit_endpoint_delegates_to_orchestrator(self):
        orchestrator = FakeOrchestrator()
        payload = {"request_id": "req_001"}

        result = audit_endpoint(payload, orchestrator=orchestrator)

        self.assertEqual(0, result["code"])
        self.assertEqual([payload], orchestrator.requests)

    def test_mock_rag_client_uses_the_same_contract_as_real_rag(self):
        cases = [{"case_id": "case_001", "title": "示例案例"}]
        client = MockRagClient(cases=cases)
        request = {"query": "测试文案", "industry": "游戏", "matched_rules": [], "top_k": 3}

        result = client.search(request)

        self.assertEqual({"code": 0, "msg": "ok", "data": {"cases": cases}}, result)
        self.assertEqual([request], client.requests)


if __name__ == "__main__":
    unittest.main()
