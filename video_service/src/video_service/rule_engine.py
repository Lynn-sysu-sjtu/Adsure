"""Idempotent adapter to the central rule engine."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from .schemas import EvidenceBundle, RuleEngineResult


def _audit_payload(bundle: EvidenceBundle) -> dict[str, Any]:
    # The current rule engine exposes the Feishu v0.2 /audit text contract.
    # Video evidence is sent as structured text plus evidence IDs; the rule
    # engine remains the only component producing risk/legal conclusions.
    lines = []
    for unit in bundle.evidence_units:
        prefix = {
            "audio_transcript": "口播",
            "frame_ocr": "画面文字",
            "visual_observation": "画面观察",
            "material_text": "材料",
            "system": "系统",
        }.get(unit.source_type, "证据")
        timestamp = ""
        if unit.start_ms is not None and unit.end_ms is not None:
            timestamp = f"[{unit.start_ms/1000:.2f}-{unit.end_ms/1000:.2f}s]"
        lines.append(f"{prefix}{timestamp}（{unit.evidence_id}）：{unit.text}")
    return {
        "record_id": bundle.record_id,
        "mode": "标准",
        "industry": "美妆" if bundle.extractor_version.ocr else "通用",
        "urgency": "普通",
        "material_type": "短视频",
        "product_category": "视频解析证据",
        "platform": ["规则引擎联调"],
        "content": "\n".join(lines)[: int(os.getenv("RULE_ENGINE_MAX_CONTENT", "18000"))],
        "supplement": json.dumps({
            "request_id": bundle.request_id,
            "material_id": bundle.material_id,
            "file_sha256": bundle.file_sha256,
            "coverage": bundle.coverage.model_dump(),
            "evidence_count": len(bundle.evidence_units),
            "extractor_version": bundle.extractor_version.model_dump(),
        }, ensure_ascii=False)[:4000],
    }


def invoke_rule_engine(bundle: EvidenceBundle) -> RuleEngineResult:
    base_url = os.getenv("RULE_ENGINE_URL", "").rstrip("/")
    if not base_url:
        return RuleEngineResult(status="skipped", request_id=bundle.request_id,
                                request_payload=payload,
                                error_code="rule_engine_not_configured",
                                error_message="RULE_ENGINE_URL 未配置；不得输出最终审核结论")
    api_key = os.getenv("RULE_ENGINE_API_KEY", "")
    attempts = int(os.getenv("RULE_ENGINE_RETRIES", "2")) + 1
    timeout_connect = float(os.getenv("RULE_ENGINE_CONNECT_TIMEOUT", "5"))
    timeout_read = float(os.getenv("RULE_ENGINE_READ_TIMEOUT", "30"))
    payload = _audit_payload(bundle)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(trust_env=False, timeout=httpx.Timeout(timeout_read, connect=timeout_connect),
                              follow_redirects=False) as client:
                response = client.post(
                    base_url.rstrip("/") + "/audit",
                    json=payload,
                    headers={
                        "X-API-Key": api_key,
                        "X-Request-ID": bundle.request_id,
                        "Idempotency-Key": bundle.material_id,
                        "Content-Type": "application/json",
                    },
                )
            response.raise_for_status()
            body = response.json()
            if body.get("code") != 0:
                raise RuntimeError(f"rule_engine_code_{body.get('code')}")
            return RuleEngineResult(status="completed", request_id=bundle.request_id,
                                    response=body, request_payload=payload, attempts=attempt)
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{str(exc)[:200]}"
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
    return RuleEngineResult(status="failed", request_id=bundle.request_id,
                            request_payload=payload,
                            error_code="rule_engine_unavailable",
                            error_message=last_error, attempts=attempts)
