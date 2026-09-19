PYTHON312 ?= python3.12
HANDOFF_PYTHON ?= .venv-handoff/bin/python
HANDOFF_OUTPUT ?= data/video_mvp/handoff_review.json

.PHONY: setup setup-semantic setup-handoff setup-handoff-video fetch extract clean import-excel import-sector-docx build-audit-cases validate-audit-cases audit-cases validate chunks semantic-index evaluate-retrieval sample-chunks rule-mapping-queue test test-rag test-audit-contract test-platform-rules test-video-mvp test-handoff case-crawler handoff-review-demo handoff-review-job preflight-rag smoke-rag setup-rag-models test-embedding serve video-mvp video-mvp-cli pipeline candidate-pipeline sector-candidate-pipeline

setup:
	pip install -r requirements.txt

setup-semantic:
	pip install -r requirements-semantic.txt

setup-handoff:
	$(PYTHON312) -m venv .venv-handoff
	.venv-handoff/bin/python -m pip install -r requirements-handoff.txt

setup-handoff-video: setup-handoff
	.venv-handoff/bin/python -m pip install -r backend/requirements-local-video.txt

fetch:
	python src/fetch_cases.py

extract:
	python src/extract_text.py

clean:
	python3 src/clean_cases.py --mode mock

import-excel:
	python3 src/import_case_excel.py

import-sector-docx:
	python3 src/import_sector_docx.py

build-audit-cases:
	python3 src/build_audit_test_cases.py

validate-audit-cases:
	python3 src/validate_audit_cases.py

audit-cases: build-audit-cases validate-audit-cases

validate:
	python3 src/validate_cases.py

chunks:
	python3 src/build_chunks.py

semantic-index:
	python3 -m src.semantic_index

evaluate-retrieval:
	python3 -m src.evaluate_retrieval

sample-chunks:
	python3 src/build_chunks.py --structured-samples-dir data/structured_samples --chunks-dir data/chunks_samples

rule-mapping-queue:
	python3 -m src.export_rule_mapping_queue

test:
	python3 src/test_retrieval.py

serve:
	uvicorn src.api:app --host "$${RAG_HOST:-127.0.0.1}" --port "$${RAG_PORT:-8505}"

video-mvp:
	./scripts/start_video_mvp.sh

video-mvp-cli:
	.venv-video/bin/python -m src.video_mvp.cli "$${VIDEO}" --output "$${OUTPUT:-data/video_mvp/manual_run}" --industry "$${INDUSTRY:-一般行业}" --sample-interval "$${SAMPLE_INTERVAL:-0.5}"

test-rag:
	python3 -m unittest tests.test_api -v

test-audit-contract:
	python3 -m unittest tests.test_audit_contract -v

test-platform-rules:
	python3 -m unittest tests.test_platform_rules -v

test-video-mvp:
	.venv-video/bin/python -m unittest tests.test_video_mvp tests.test_video_mvp_v2 tests.test_video_mvp_v3 tests.test_video_feishu_adapter tests.test_video_volc_asr tests.test_video_rapidocr_env -v

test-handoff:
	$(HANDOFF_PYTHON) -m pytest backend/tests -q

case-crawler:
	$(HANDOFF_PYTHON) backend/scripts/crawl_samr.py $(CRAWLER_ARGS)

handoff-review-demo:
	$(HANDOFF_PYTHON) backend/scripts/run_review.py --demo --llm mock --out $(HANDOFF_OUTPUT)

handoff-review-job:
	$(HANDOFF_PYTHON) backend/scripts/run_review.py --job "$(VIDEO_JOB)" --llm mock --out $(HANDOFF_OUTPUT)

preflight-rag:
	python3 -m src.preflight_rag

smoke-rag:
	./scripts/smoke_rag_service.sh

setup-rag-models:
	bash scripts/setup_rag_models.sh

test-embedding:
	.venv-video/bin/python -m unittest tests.test_zhipu_embedding -v

pipeline: fetch extract clean validate chunks sample-chunks test

candidate-pipeline:
	python3 src/import_case_excel.py
	python3 src/validate_cases.py
	python3 src/build_chunks.py
	python3 src/test_retrieval.py --query "普通食品 宣传 降血糖"

sector-candidate-pipeline:
	python3 src/import_sector_docx.py
	python3 src/validate_cases.py
	python3 src/build_chunks.py
	python3 src/test_retrieval.py --query "游戏 抽奖 概率 公示 虚假宣传"
	python3 src/test_retrieval.py --query "化妆品 宣传 杀菌 消炎 医疗用语"
	python3 src/test_retrieval.py --query "保健品 会销 降血压 心脑血管"
