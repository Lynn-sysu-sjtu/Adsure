.PHONY: setup fetch extract clean import-excel import-sector-docx build-audit-cases validate-audit-cases audit-cases validate chunks sample-chunks rule-mapping-queue test test-rag preflight-rag smoke-rag serve pipeline candidate-pipeline sector-candidate-pipeline

setup:
	pip install -r requirements.txt

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

sample-chunks:
	python3 src/build_chunks.py --structured-samples-dir data/structured_samples --chunks-dir data/chunks_samples

rule-mapping-queue:
	python3 -m src.export_rule_mapping_queue

test:
	python3 src/test_retrieval.py

serve:
	uvicorn src.api:app --host "$${RAG_HOST:-127.0.0.1}" --port "$${RAG_PORT:-8505}"

test-rag:
	python3 -m unittest tests.test_api -v

preflight-rag:
	python3 -m src.preflight_rag

smoke-rag:
	./scripts/smoke_rag_service.sh

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
