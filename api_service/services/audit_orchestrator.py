from copy import deepcopy


class AuditOrchestrator:
    def __init__(self, rule_engine_client, rag_client, rag_top_k=3):
        self.rule_engine_client = rule_engine_client
        self.rag_client = rag_client
        self.rag_top_k = rag_top_k

    def audit(self, payload):
        rule_response = self.rule_engine_client.audit(payload)
        if rule_response.get("code") != 0 or not isinstance(rule_response.get("data"), dict):
            return rule_response

        result = deepcopy(rule_response)
        data = result["data"]
        rag_request = self._build_rag_request(payload, data)
        try:
            rag_response = self.rag_client.search(rag_request)
            rag_data = rag_response.get("data") if isinstance(rag_response, dict) else None
            cases = rag_data.get("cases", []) if isinstance(rag_data, dict) else []
            if rag_response.get("code") != 0 or not isinstance(cases, list):
                raise ValueError("RAG service returned an invalid response")
            data["related_cases"] = cases
            data["case_search_status"] = "ok" if cases else "empty"
        except Exception:
            data["related_cases"] = []
            data["case_search_status"] = "unavailable"
        return result

    def _build_rag_request(self, payload, audit_data):
        material = payload.get("material") if isinstance(payload.get("material"), dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        matched_rules = []
        for rule in audit_data.get("matched_rules", []) or []:
            if not isinstance(rule, dict):
                continue
            matched_rules.append(
                {
                    "rule_id": rule.get("rule_id"),
                    "dimension": rule.get("dimension"),
                }
            )
        return {
            "tenant_id": payload.get("tenant_id") or "adsure_demo",
            "query": material.get("content", ""),
            "industry": context.get("industry", ""),
            "matched_rules": matched_rules,
            "top_k": self.rag_top_k,
        }
