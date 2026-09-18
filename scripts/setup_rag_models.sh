#!/usr/bin/env bash
# Pre-download the semantic encoder so the RAG service does not need
# network access on first request. Models land in HF_HOME (see rag.env).
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL="${CASE_ENGINE_EMBEDDING_MODEL:-BAAI/bge-base-zh-v1.5}"
PYTHON="${PYTHON:-python3}"
echo "Pre-downloading embedding model: $MODEL (HF_HOME=${HF_HOME:-default})"
HF_HUB_ENABLE_HF_TRANSFER=0 "$PYTHON" - "$MODEL" <<'PY'
import os, sys
import transformers.utils.import_utils as ti
ti._torchvision_available = False
from sentence_transformers import SentenceTransformer
name = sys.argv[1]
model = SentenceTransformer(name, local_files_only=False)
print("ready", name, "dim", model.get_sentence_embedding_dimension())
PY
