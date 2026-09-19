#!/usr/bin/env bash
# Prepare the RAG semantic encoder.
#  - provider=zhipu: verify BigModel embedding API connectivity (no local download)
#  - provider=local (default fallback): pre-download the bge sentence-transformer
set -euo pipefail
cd "$(dirname "$0")/.."
PROVIDER="${CASE_ENGINE_EMBEDDING_PROVIDER:-local}"
PYTHON="${PYTHON:-.venv-video/bin/python}"

if [[ "$PROVIDER" == "zhipu" ]]; then
  echo "Embedding provider=zhipu (BigModel API); verifying connectivity, no local model download."
  CASE_ENGINE_EMBEDDING_PROVIDER=zhipu "$PYTHON" - <<'PY'
import os
from src.semantic_index import configured_encoder
encode = configured_encoder(os.getenv("CASE_ENGINE_EMBEDDING_MODEL", "embedding-3"))
rows = encode(["广告合规风险检索连通性测试"])
print("zhipu embedding ready, dim", len(rows[0]) if rows else 0)
PY
  exit 0
fi

MODEL="${CASE_ENGINE_EMBEDDING_MODEL:-BAAI/bge-base-zh-v1.5}"
echo "Pre-downloading local embedding model: $MODEL (HF_HOME=${HF_HOME:-default})"
HF_HUB_ENABLE_HF_TRANSFER=0 "$PYTHON" - "$MODEL" <<'PY'
import sys
import transformers.utils.import_utils as ti
ti._torchvision_available = False
from sentence_transformers import SentenceTransformer
name = sys.argv[1]
model = SentenceTransformer(name, local_files_only=False)
print("ready", name, "dim", model.get_sentence_embedding_dimension())
PY
