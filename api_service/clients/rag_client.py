import requests


class RagClient:
    def __init__(self, base_url, api_key="", timeout=5, session=None):
        self.url = base_url.rstrip("/") + "/search"
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def search(self, payload):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        response = self.session.post(
            self.url,
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class MockRagClient:
    def __init__(self, cases=None):
        self.cases = list(cases or [])
        self.requests = []

    def search(self, payload):
        self.requests.append(payload)
        return {"code": 0, "msg": "ok", "data": {"cases": list(self.cases)}}
