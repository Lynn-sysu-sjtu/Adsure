# -*- coding: utf-8 -*-
"""MVP /audit API facade for the rule engine.

This module intentionally keeps the core entrypoint as a plain function so it
can be called by tests, scripts, or a future Feishu worker without requiring a
web framework. If FastAPI is installed, it also exposes `app`.
"""

import json
import os
import secrets
import sys
from typing import Optional

from rule_engine import AuditInputError, audit


def _auth_failure(msg):
    return {"code": -1, "msg": msg, "data": None}


def validate_api_key(x_api_key):
    expected = os.getenv("ADSURE_API_KEY")
    if not expected:
        return _auth_failure("规则引擎未配置 API Key")
    if not x_api_key or not secrets.compare_digest(str(x_api_key), expected):
        return _auth_failure("API Key 无效或缺失")
    return None


def audit_endpoint(payload, base_dir=None):
    try:
        return audit(payload, base_dir=base_dir)
    except AuditInputError as exc:
        return {"code": -1, "msg": str(exc), "data": None}
    except Exception as exc:  # pragma: no cover - defensive API boundary.
        return {"code": -1, "msg": f"规则引擎内部错误：{exc}", "data": None}


try:  # Optional dependency; the local function is the stable MVP contract.
    from fastapi import FastAPI, Header

    app = FastAPI(title="Adsure Rule Engine MVP")

    @app.post("/audit")
    def post_audit(payload: dict, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
        auth_error = validate_api_key(x_api_key)
        if auth_error:
            return auth_error
        return audit_endpoint(payload)

except Exception:  # pragma: no cover - FastAPI may not be installed locally.
    app = None


def main():
    payload = json.load(sys.stdin)
    response = audit_endpoint(payload)
    json.dump(response, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

