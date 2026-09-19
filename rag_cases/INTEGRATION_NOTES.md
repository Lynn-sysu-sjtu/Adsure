# RAG Integration Notes

## Source versions

- RAG production base: `codex/ads-penalty-rag-pipeline@1195ff0cc59c8dcd075c50d118edd1ad966550bc`
- RAG deployment improvements overlaid from: `codex/video-evidence-service-20260920@f49e670`
  - Zhipu BigModel embedding support
  - `scripts/setup_rag_models.sh`
  - `scripts/rebuild_zhipu_index.sh`
  - `tests/test_zhipu_embedding.py`

## Production target configuration

```text
CASE_ENGINE_RETRIEVAL_MODE=hybrid
CASE_ENGINE_EMBEDDING_PROVIDER=zhipu
CASE_ENGINE_EMBEDDING_MODEL=embedding-3
CASE_ENGINE_EMBEDDING_DIMENSIONS=2048
CASE_ENGINE_REQUIRE_SEMANTIC=1
```

The Zhipu API key belongs in `/etc/adsure/rag-secret.env` on the server and
must never be committed. The template is:

```text
deploy/rag-secret.env.example
```

## Zhipu semantic index rebuild

`data/chunks/production_semantic_index.json` has been rebuilt with the Zhipu
BigModel API:

```text
provider          = zhipu
model_name        = embedding-3
dimension         = 2048
documents         = 250
chunk_fingerprint = bcb297cdd822de9b   # unchanged: only vectors were recomputed
```

Before this rebuild the committed index was the historical BAAI one
(`BAAI/bge-base-zh-v1.5`, 768 dimensions, 250 documents); that combination is
incompatible with `embedding-3` and is no longer shipped.

To rebuild again on a machine with network access and the Zhipu key, run:

```bash
cd rag_cases
cp .env.zhipu.local.example .env.zhipu.local
# Fill ZHIPU_API_KEY in .env.zhipu.local
PYTHON=/path/to/venv/bin/python bash scripts/rebuild_zhipu_index.sh
PYTHON=/path/to/venv/bin/python bash scripts/preflight_zhipu.sh
```

`scripts/preflight_zhipu.sh` reads `/etc/adsure/rag-secret.env` and
`.env.zhipu.local`, then runs the production preflight with the Zhipu
configuration. `make rebuild-zhipu-index` / `make preflight-zhipu` are the
equivalent shortcuts.

Expected summary:

```text
provider=zhipu
model=embedding-3
dimension=2048
documents=250
```

The rebuild script fails if the key is missing, the API is unavailable, the
model is not `embedding-3`, the dimension is not `2048`, or the document count
is zero.

## Strict preflight

`src/preflight_rag.py` now validates:

- `retrieval=hybrid`
- `provider=zhipu`
- `model=embedding-3`
- `dimension=2048`
- semantic index is ready (`semantic=ready`)
- Zhipu API key is configured (`ZHIPU_API_KEY` / `CASE_ENGINE_EMBEDDING_API_KEY`)

`src/api.py` refuses to start when `CASE_ENGINE_REQUIRE_SEMANTIC=1` (or
`provider=zhipu` + `retrieval=hybrid`) and the semantic index is missing, stale,
incomplete, or built with a different model or dimension. A missing key or an
unreachable Zhipu endpoint also fails the preflight. It never silently degrades
to lexical and still reports `preflight ok`.

The ASGI app is now built lazily through a module-level `__getattr__`
(PEP 562). `uvicorn src.api:app` still builds the app and still refuses to start
on a bad configuration, while preflight and evaluation scripts can import
`src.api` and print the full case/chunk report instead of crashing during import.

### Evidence: Zhipu mode fails until the index is rebuilt

```text
$ CASE_ENGINE_RETRIEVAL_MODE=hybrid CASE_ENGINE_EMBEDDING_PROVIDER=zhipu \
  CASE_ENGINE_EMBEDDING_MODEL=embedding-3 CASE_ENGINE_EMBEDDING_DIMENSIONS=2048 \
  CASE_ENGINE_REQUIRE_SEMANTIC=1 python -m src.preflight_rag     # no ZHIPU_API_KEY
RAG production preflight failed:
- CASE_ENGINE_EMBEDDING_PROVIDER=zhipu 但 ZHIPU_API_KEY/CASE_ENGINE_EMBEDDING_API_KEY 未配置
- 语义索引模型不匹配：model_mismatch_index=BAAI/bge-base-zh-v1.5_configured=embedding-3
- 语义检索未就绪：requested=hybrid, status=model_mismatch_index=BAAI/bge-base-zh-v1.5_configured=embedding-3
exit=1

$ ...same, with ZHIPU_API_KEY set to a placeholder
RAG production preflight failed:
- 语义索引模型不匹配：model_mismatch_index=BAAI/bge-base-zh-v1.5_configured=embedding-3
- 语义检索未就绪：requested=hybrid, status=model_mismatch_index=BAAI/bge-base-zh-v1.5_configured=embedding-3
exit=1

$ uvicorn src.api:app   # same configuration
RuntimeError: 语义检索未就绪，拒绝启动：requested=hybrid,
status=model_mismatch_index=BAAI/bge-base-zh-v1.5_configured=embedding-3
```

### Evidence: local BAAI baseline (historical, before the rebuild)

```text
$ CASE_ENGINE_INDEX_SCOPE=production CASE_ENGINE_RETRIEVAL_MODE=hybrid \
  CASE_ENGINE_EMBEDDING_PROVIDER=local ADSURE_API_KEY=tmp-test \
  python -m src.preflight_rag
RAG production preflight ok: cases=125 public_cases=125 chunks=250
index=262491abf7e8e200 retrieval=hybrid semantic=ready
provider=local model=BAAI/bge-base-zh-v1.5 dimension=768
```

```text
$ CASE_ENGINE_INDEX_SCOPE=production CASE_ENGINE_RETRIEVAL_MODE=lexical \
  ADSURE_API_KEY=tmp-test python -m src.preflight_rag
RAG production preflight ok: cases=125 public_cases=125 chunks=250
index=262491abf7e8e200 retrieval=lexical semantic=disabled
provider=local model=None dimension=None
```

### Evidence: Zhipu mode passes after the rebuild

```text
$ ZHIPU_INDEX_SUMMARY={"provider": "zhipu", "model": "embedding-3",
  "dimension": 2048, "documents": 250, "chunk_fingerprint": "bcb297cdd822de9b"}

$ CASE_ENGINE_INDEX_SCOPE=production CASE_ENGINE_RETRIEVAL_MODE=hybrid \
  CASE_ENGINE_EMBEDDING_PROVIDER=zhipu CASE_ENGINE_EMBEDDING_MODEL=embedding-3 \
  CASE_ENGINE_EMBEDDING_DIMENSIONS=2048 CASE_ENGINE_REQUIRE_SEMANTIC=1 \
  python -m src.preflight_rag
RAG production preflight ok: cases=125 public_cases=125 chunks=250
index=262491abf7e8e200 retrieval=hybrid semantic=ready
provider=zhipu model=embedding-3 dimension=2048
```

`semantic=ready` is only reported after the preflight has actually embedded a
probe query through the Zhipu API, so it also proves the key and endpoint work.
None of the following appear in the output: 索引加载失败、切片找不到结构化案例、
原文不存在、production 读取 structured_candidates、正式索引为空.

## Test status

### Passing RAG API / preflight tests

```text
tests.test_api tests.test_preflight_rag
29 tests OK
```

New strict-preflight tests added in this branch:

1. `test_zhipu_without_api_key_fails`
2. `test_zhipu_index_model_mismatch_fails`
3. `test_zhipu_index_dimension_mismatch_fails`
4. `test_zhipu_index_matching_embedding_3_passes`
5. `test_zhipu_api_failure_fails_instead_of_silent_lexical`

### Full RAG suite on macOS

```text
Ran 166 tests
FAILED (failures=4, errors=1)
```

(161 tests before the 5 strict-preflight tests were added; the same 5 historical
failures remain, so this branch adds no new failures.)

Failures/errors and classification:

1. `test_corrected_judge_package.CorrectedJudgePackageTests.test_generated_package_matches_acceptance_contract`
   - Missing local submission artifact:
     `参赛提交材料/adsure_judge_test_cases_3条_可验收版.json`
   - Historical/local packaging issue, not a RAG service runtime failure.

2. `test_demo_production_promotion.DemoProductionPromotionTests.test_demo_cases_enter_production_without_rewriting_source_status`
   - Demo allowlist expectations no longer match the current production catalog.
   - Historical test-data mismatch.

3. `test_demo_production_promotion.DemoProductionPromotionTests.test_three_judge_queries_hit_expected_case_first_in_production`
   - Expected demo case set differs from current production chunks.
   - Historical test-data mismatch.

4. `test_production_catalog.ProductionCatalogTests.test_official_catalog_and_demo_allowlist_build_production_chunks`
   - Expected production case ID set differs from current production chunks.
   - Historical test-data mismatch.

5. `test_retrieval_quality.RetrievalQualityTests.test_curated_precision_regressions`
   - Negative case `negative_unsupported_sales_claim` returns two cases.
   - Pre-existing failure on `1195ff0`.

The Windows teammate run reported `6 failures, 2 errors`; the additional
failures/errors are environment-specific (CRLF hash changes and Windows file
locking) and are not treated as Linux cloud blockers.

## Video service notes

The video service is packaged separately as `video_service/`. The systemd
unit uses `.venv-video/bin/python` consistently, and the model installation
command is:

```bash
bash scripts/setup_video_models.sh
```

Follow-up fixes after the dev merge review:

1. PyAV (`av`) is now declared in `video_service/requirements-video.txt`
   (`av>=14,<19`) and checked by `scripts/preflight_video.py`.
2. `video_service/data/schemas/audit_response_v0.2.schema.json` is now committed
   (byte-identical to the copy under `rag_cases/data/schemas/`), and the
   preflight checks that it exists.
3. `scripts/preflight_video.py` now verifies every `raw_sha256` in
   `data/platform_rules/manifest_2026-09-04.json`, so a converted evidence file
   fails at preflight instead of silently breaking provenance.
4. Evidence bytes are protected from line-ending conversion: `-text` rules were
   added for `data/platform_rules/raw_*` and `datasets/golden/**`
   (`rag_cases/.gitattributes` protects `data/raw_*`, `data/structured*` and
   `data/platform_rules` the same way). All 12 manifest hashes match the
   committed blobs.
5. The 6 files that were stored with CRLF while declared `text eol=lf` were
   normalized to LF (`report.py`, `L2_industry.yaml`, `demo_pipeline.py`,
   `test_legalref.py`, `test_crawler.py`, `candidate_inventory.csv`).

Video tests on macOS:

```text
tests.test_video_service tests.test_video_mvp tests.test_video_mvp_v2
tests.test_video_mvp_v3 tests.test_video_volc_asr tests.test_video_rapidocr_env
tests.test_video_feishu_adapter
86 tests OK
```

(55 of these are the four modules required by the review; the feishu contract
module had been silently skipped because its schema file was missing.)

Video production preflight on macOS fails on disk space only
(`free < 2 GiB`); the PyAV, schema and provenance checks all pass. Linux
55-test verification and video production preflight are still required on the
Linux cloud host.

## Deployment roots

```text
rag_cases/     -> /opt/adsure-rag
video_service/ -> /opt/adsure-video-review
```
