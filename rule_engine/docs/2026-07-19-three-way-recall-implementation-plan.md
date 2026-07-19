# Three-Way Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded LLM catalog recall path for open-ended advertising rules, merge it with keyword and semantic recall, reduce the final DeepSeek judgment pool, and preserve the `/audit` contract.

**Architecture:** Keep full deduplicated recall results for output, routing, and risk synthesis. Run semantic recall and catalog recall in parallel, merge all channels by parent `rule_id`, then select a bounded internal judgment pool for the existing DeepSeek subsumption call. Catalog recall is disabled by default and fails open to an empty result.

**Tech Stack:** Python standard library, `unittest`, existing DeepSeek and Zhipu clients, JSON rule assets.

---

### Task 1: Parent-rule merge and judgment-pool selection

**Files:**
- Modify: `src/rule_engine.py`
- Create: `src/test_recall_merge_and_judgment_pool.py`

- [ ] Write tests proving duplicate keyword parents collapse, hit reasons merge, full matched rules remain available, and the internal judgment pool is capped without changing routing inputs.
- [ ] Run `py -3 -m unittest test_recall_merge_and_judgment_pool.py` and confirm the tests fail for missing helpers.
- [ ] Implement `_merge_recalled_rules()` and `_select_judgment_rules()` with environment-configurable limit.
- [ ] Route only the selected pool into `_judge_with_config()` while preserving full recalled rules for `matched_rules`, routing, fact advice, and risk synthesis.
- [ ] Run the targeted test and existing rule-engine, risk, semantic, and contract tests.

### Task 2: Open-ended catalog metadata and generator

**Files:**
- Modify: `jsonbase/20260623_中华人民共和国广告法_通用规则_v1.json`
- Create: `src/catalog_rule_directory.py`
- Create: `src/test_catalog_rule_directory.py`

- [ ] Write tests requiring exactly the approved eight catalog rules, unique IDs, non-empty texts no longer than80 Chinese characters, and content trigger layers only.
- [ ] Run the test and confirm it fails before metadata/generator implementation.
- [ ] Add `catalog_recall_enabled`, `catalog_text`, and `catalog_group` to the eight approved parent rules.
- [ ] Implement `build_catalog_directory(rules, request)` with existing context applicability filtering.
- [ ] Run targeted asset and generator tests.

### Task 3: Mock catalog recall and validated output

**Files:**
- Create: `src/catalog_recall.py`
- Create: `src/test_catalog_recall.py`

- [ ] Write tests for disabled behavior, mock selection, unknown-ID filtering, deduplication, result limits, malformed JSON, and exception fallback.
- [ ] Run the tests and confirm failure.
- [ ] Implement catalog prompt construction, strict JSON parsing, allowed-ID validation, and a deterministic mock backend.
- [ ] Mark catalog-only results with `llm_catalog` recall provenance.
- [ ] Run targeted tests.

### Task 4: DeepSeek backend and parallel orchestration

**Files:**
- Modify: `src/catalog_recall.py`
- Modify: `src/rule_engine.py`
- Create: `src/test_three_way_recall_orchestration.py`

- [ ] Write tests using fake semantic/catalog functions to prove both branches execute, results merge once per parent, catalog timeout returns empty, and catalog exceptions do not fail `/audit`.
- [ ] Run the tests and confirm failure.
- [ ] Add the DeepSeek backend through the existing `DeepSeekClient`, using a catalog-specific model and timeout.
- [ ] Use `ThreadPoolExecutor(max_workers=2)` to run semantic and catalog recall concurrently after keyword recall.
- [ ] Keep feature-disabled behavior identical to the current engine.
- [ ] Run orchestration and contract tests.

### Task 5: Baseline diagnostics and verification

**Files:**
- Modify: `src/run_engine_baseline_eval.py`
- Modify: `src/test_engine_baseline_eval.py`

- [ ] Write tests for optional internal metrics: matched-rule count, judgment-pool count, catalog-matched cases, and latency summaries.
- [ ] Implement report-only diagnostics without changing `/audit` fields.
- [ ] Run all local unit tests with local semantic and mock LLM backends.
- [ ] Run the 24-case Zhipu＋Mock baseline with catalog disabled and require recall/dimension/routing 24/24.
- [ ] Run the 24-case Zhipu＋DeepSeek baseline with catalog enabled and compare latency, risk agreement, outside-rule risks, and catalog-only recoveries.

### Task 6: Final contract check

**Files:**
- Modify only if a regression test exposes a defect: `src/test_audit_contract_semantic_scenarios.py`

- [ ] Compare the existing `/audit` required key set before and after the change.
- [ ] Confirm `CASE-SEM-006` returns one `GEN-GOOD-CUSTOMS-001` parent.
- [ ] Run `git diff --check` and inspect the final diff for unintended Feishu or knowledge-graph changes.
