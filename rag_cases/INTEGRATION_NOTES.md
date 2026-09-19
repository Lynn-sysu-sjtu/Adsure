# RAG Integration Notes

## Source versions

- RAG production base: `codex/ads-penalty-rag-pipeline@1195ff0cc59c8dcd075c50d118edd1ad966550bc`
- RAG deployment improvements overlaid from: `codex/video-evidence-service-20260920@f49e670`
  - Zhipu BigModel embedding support (`CASE_ENGINE_EMBEDDING_PROVIDER=zhipu`)
  - `scripts/setup_rag_models.sh`
  - `tests/test_zhipu_embedding.py`

## Verified production preflight

Command:

```bash
CASE_ENGINE_INDEX_SCOPE=production \
CASE_ENGINE_DATA_DIR=./data \
ADSURE_API_KEY=test \
CASE_ENGINE_RETRIEVAL_MODE=hybrid \
CASE_ENGINE_EMBEDDING_PROVIDER=local \
CASE_ENGINE_EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5 \
python -m src.preflight_rag
```

Result:

```text
RAG production preflight ok:
cases=125
public_cases=125
chunks=250
index=262491abf7e8e200
retrieval=hybrid
semantic=ready
```

## Semantic index compatibility

The committed `data/chunks/production_semantic_index.json` is:

```text
model_name = BAAI/bge-base-zh-v1.5
dimension  = 768
documents  = 250
```

If deploying with `CASE_ENGINE_EMBEDDING_PROVIDER=zhipu` and
`CASE_ENGINE_EMBEDDING_MODEL=embedding-3` (2048 dimensions), rebuild the
semantic index first with the same provider. Otherwise keep:

```text
CASE_ENGINE_EMBEDDING_PROVIDER=local
CASE_ENGINE_EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5
```

## Test status

Passing:

```text
tests.test_api
tests.test_preflight_rag
24 tests OK
```

Known pre-existing failure in `1195ff0`:

```text
tests.test_retrieval_quality.test_curated_precision_regressions
negative_unsupported_sales_claim expected [], got two cases
```

This failure exists on the RAG branch before the integration changes and is
recorded here for review rather than hidden.

## Deployment root

Deploy this directory as `/opt/adsure-rag`; the systemd unit assumes:

```text
WorkingDirectory=/opt/adsure-rag
ExecStart=/opt/adsure-rag/.venv/bin/uvicorn src.api:app --host 127.0.0.1 --port 8505
```
