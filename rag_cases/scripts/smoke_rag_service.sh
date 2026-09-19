#!/usr/bin/env bash
set -euo pipefail

base_url="${CASE_ENGINE_URL:-http://127.0.0.1:8505}"
base_url="${base_url%/}"
api_key="${CASE_ENGINE_API_KEY:-${ADSURE_API_KEY:-}}"
timeout_seconds="${CASE_ENGINE_SMOKE_TIMEOUT:-8}"

if [[ -z "${api_key}" ]]; then
  echo "CASE_ENGINE_API_KEY 或 ADSURE_API_KEY 未配置" >&2
  exit 2
fi

health_payload="$(
  curl -fsS \
    --max-time "${timeout_seconds}" \
    "${base_url}/health"
)"

printf '%s' "${health_payload}" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
if payload.get("status") != "ok":
    raise SystemExit("health status is not ok: {}".format(payload.get("status")))
if payload.get("candidate_data") is not False:
    raise SystemExit("candidate index must not be enabled for production smoke")
checks = payload.get("checks") or {}
if checks.get("index") != "ok" or checks.get("api_key") != "configured":
    raise SystemExit(f"health checks failed: {checks}")
if not payload.get("index_version"):
    raise SystemExit("health response is missing index_version")
print(
    "health ok:",
    "scope={}".format(payload.get("index_scope")),
    "cases={}".format(payload.get("case_count")),
    "chunks={}".format(payload.get("chunk_count")),
    "index={}".format(payload.get("index_version")),
)
'

retrieve_payload="$(
  curl -fsS \
    --max-time "${timeout_seconds}" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${api_key}" \
    -H "X-Request-ID: deployment-smoke" \
    -d '{"content":"普通食品宣称降血糖并治疗高血压","industry":"保健食品","platform":["抖音"],"top_k":3}' \
    "${base_url}/cases/retrieve"
)"

printf '%s' "${retrieve_payload}" | python3 -c '
import json
import sys

payload = json.load(sys.stdin)
if payload.get("code") != 0:
    raise SystemExit(
        "retrieve failed: code={} msg={}".format(
            payload.get("code"),
            payload.get("msg"),
        )
    )
data = payload.get("data") or {}
cases = data.get("cases")
meta = data.get("retrieval_meta") or {}
if not isinstance(cases, list):
    raise SystemExit("retrieve response data.cases must be an array")
if meta.get("index_scope") != "production":
    raise SystemExit("unexpected index scope: {}".format(meta.get("index_scope")))
if not meta.get("index_version"):
    raise SystemExit("retrieve response is missing index_version")
print(
    "retrieve ok:",
    "returned={}".format(len(cases)),
    "index={}".format(meta.get("index_version")),
)
'
