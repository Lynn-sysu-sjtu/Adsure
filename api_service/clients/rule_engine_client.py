import requests


class RuleEngineClient:
    def __init__(self, base_url, api_key, timeout=12, session=None):
        self.url = base_url.rstrip("/") + "/audit"
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()

    def audit(self, payload):
        response = self.session.post(
            self.url,
            headers={"X-API-Key": self.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
