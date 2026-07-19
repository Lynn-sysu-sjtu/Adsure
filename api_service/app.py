import os

from api_service.clients.rag_client import MockRagClient, RagClient
from api_service.clients.rule_engine_client import RuleEngineClient
from api_service.services.audit_orchestrator import AuditOrchestrator


VERSION = "0.1.0"
_default_orchestrator = None


def health_endpoint():
    return {"status": "ok", "service": "adsure-api-service", "version": VERSION}


def build_default_orchestrator():
    rule_client = RuleEngineClient(
        os.getenv("RULE_ENGINE_URL", "http://127.0.0.1:8504"),
        os.getenv("ADSURE_API_KEY", ""),
    )
    rag_backend = os.getenv("ADSURE_RAG_BACKEND", "mock").lower()
    if rag_backend == "http":
        rag_client = RagClient(
            os.getenv("RAG_SERVICE_URL", "http://127.0.0.1:8505"),
            os.getenv("RAG_SERVICE_API_KEY", ""),
        )
    else:
        rag_client = MockRagClient()
    return AuditOrchestrator(rule_client, rag_client)


def audit_endpoint(payload, orchestrator=None):
    global _default_orchestrator
    if orchestrator is None:
        if _default_orchestrator is None:
            _default_orchestrator = build_default_orchestrator()
        orchestrator = _default_orchestrator
    return orchestrator.audit(payload)


try:
    from fastapi import FastAPI

    app = FastAPI(title="Adsure Audit API", version=VERSION)

    @app.get("/health")
    def get_health():
        return health_endpoint()

    @app.post("/api/v1/audits")
    def post_audit(payload: dict):
        return audit_endpoint(payload)

except Exception:
    app = None
