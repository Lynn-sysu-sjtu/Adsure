#!/usr/bin/env bash
# Rebuild production_semantic_index.json with Zhipu BigModel embedding-3.
# The API key must come from the server secret env; never commit it.
set -euo pipefail
cd "$(dirname "$0")/.."

for env_file in /etc/adsure/rag-secret.env .env.zhipu.local; do
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1091
    . "$env_file"
    set +a
  fi
done

if [[ -z "${ZHIPU_API_KEY:-}" && -z "${CASE_ENGINE_EMBEDDING_API_KEY:-}" ]]; then
  echo "ERROR: ZHIPU_API_KEY or CASE_ENGINE_EMBEDDING_API_KEY is required." >&2
  exit 1
fi

export CASE_ENGINE_EMBEDDING_PROVIDER=zhipu
export CASE_ENGINE_EMBEDDING_MODEL=embedding-3
export CASE_ENGINE_ZHIPU_EMBEDDING_MODEL=embedding-3
export CASE_ENGINE_EMBEDDING_DIMENSIONS=2048
export CASE_ENGINE_EMBEDDING_BATCH_SIZE="${CASE_ENGINE_EMBEDDING_BATCH_SIZE:-32}"

# 找一个能 import httpx 的解释器：$PYTHON -> .venv-video -> .venv -> python3
resolve_python() {
  local candidate
  for candidate in "${PYTHON:-}" .venv-video/bin/python .venv/bin/python python3; do
    [[ -n "$candidate" ]] || continue
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c "import httpx" >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(resolve_python)" || {
  echo "ERROR: 找不到能 import httpx 的 Python 解释器。" >&2
  echo "       已尝试：${PYTHON:-<未设置>}、.venv-video/bin/python、.venv/bin/python、python3" >&2
  echo "       请显式指定，例如：" >&2
  echo "       PYTHON=/path/to/venv/bin/python bash scripts/rebuild_zhipu_index.sh" >&2
  exit 1
}
echo "using python: $PYTHON_BIN" >&2

"$PYTHON_BIN" -m src.semantic_index

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path

path = Path("data/chunks/production_semantic_index.json")
payload = json.loads(path.read_text(encoding="utf-8"))
summary = {
    "provider": "zhipu",
    "model": payload.get("model_name"),
    "dimension": payload.get("dimension"),
    "documents": payload.get("document_count"),
    "chunk_fingerprint": payload.get("chunk_fingerprint"),
}
print("ZHIPU_INDEX_SUMMARY=" + json.dumps(summary, ensure_ascii=False))
if summary["model"] != "embedding-3":
    raise SystemExit("index model mismatch: expected embedding-3")
if int(summary["dimension"] or 0) != 2048:
    raise SystemExit("index dimension mismatch: expected 2048")
if int(summary["documents"] or 0) <= 0:
    raise SystemExit("index documents must be > 0")
PY
