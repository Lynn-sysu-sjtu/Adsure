#!/usr/bin/env bash
# 以智谱生产配置运行 RAG 生产预检。
#
# 读取顺序：/etc/adsure/rag-secret.env（云服务器） -> .env.zhipu.local（本地，gitignored）。
# 语义索引必须已用同一 provider 重建（见 scripts/rebuild_zhipu_index.sh），
# 否则预检会明确失败，不会静默降级成 lexical。
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

export CASE_ENGINE_INDEX_SCOPE="${CASE_ENGINE_INDEX_SCOPE:-production}"
export CASE_ENGINE_RETRIEVAL_MODE="${CASE_ENGINE_RETRIEVAL_MODE:-hybrid}"
export CASE_ENGINE_EMBEDDING_PROVIDER="${CASE_ENGINE_EMBEDDING_PROVIDER:-zhipu}"
export CASE_ENGINE_EMBEDDING_MODEL="${CASE_ENGINE_EMBEDDING_MODEL:-embedding-3}"
export CASE_ENGINE_ZHIPU_EMBEDDING_MODEL="${CASE_ENGINE_ZHIPU_EMBEDDING_MODEL:-embedding-3}"
export CASE_ENGINE_EMBEDDING_DIMENSIONS="${CASE_ENGINE_EMBEDDING_DIMENSIONS:-2048}"
export CASE_ENGINE_REQUIRE_SEMANTIC="${CASE_ENGINE_REQUIRE_SEMANTIC:-1}"
export CASE_ENGINE_DATA_DIR="${CASE_ENGINE_DATA_DIR:-$PWD/data}"

# 本地自检时若没有服务密钥，用一个占位值即可（预检只校验"已配置"）。
if [[ -z "${ADSURE_API_KEY:-}" ]]; then
  export ADSURE_API_KEY="preflight-local-check"
fi

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
  echo "       请显式指定，例如：PYTHON=/path/to/venv/bin/python bash scripts/preflight_zhipu.sh" >&2
  exit 1
}

exec "$PYTHON_BIN" -m src.preflight_rag "$@"
