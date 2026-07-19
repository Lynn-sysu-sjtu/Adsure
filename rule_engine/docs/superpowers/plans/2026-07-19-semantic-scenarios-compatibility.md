# Semantic Scenarios Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backward-compatible multi-scenario vector recall, deduplicate scenario hits to one parent rule, and preserve the existing `/audit` request and response contract.

**Architecture:** Rules retain `recall.vector_text` for legacy readers and may add `recall.semantic_scenarios`. The vector index expands each enabled scenario into its own record; semantic recall scores scenario records and collapses them by parent `rule_id`, returning the existing `(rule, hits)` shape. The public audit response remains unchanged.

**Tech Stack:** Python 3, unittest, JSON rule assets, FastAPI facade, cached embedding index.

---

### Task 1: Specify scenario expansion and legacy fallback

**Files:**
- Modify: `src/test_rule_vector_index.py`
- Modify: `src/rule_vector_index.py`

- [ ] Add a failing test proving one parent rule with two enabled scenarios produces two vector records carrying `rule_id`, `rule_uid`, and `scenario_id`.
- [ ] Add a failing test proving a rule without scenarios still produces one legacy `rule_summary` vector from `recall.vector_text`.
- [ ] Run `python -m unittest test_rule_vector_index.py` and confirm the new tests fail because scenario expansion is not implemented.
- [ ] Implement a shared iterator that expands enabled scenarios and falls back to the parent `vector_text` only when no enabled scenario exists.
- [ ] Run `python -m unittest test_rule_vector_index.py` and confirm the index tests pass.

### Task 2: Deduplicate semantic scenario hits by parent rule

**Files:**
- Modify: `src/test_semantic_recall.py`
- Modify: `src/test_rule_vector_index.py`
- Modify: `src/semantic_recall.py`

- [ ] Add a failing local-recall test where two scenarios from one parent both match but the function returns that parent once.
- [ ] Add a failing cached-embedding test proving index lookup distinguishes scenario records and chooses the best score for the parent.
- [ ] Run the targeted tests and confirm failure is caused by the current single-vector assumption.
- [ ] Update semantic recall to score expanded records, retain the best scenario per parent, and return semantic hit strings that still begin with `semantic` so `rule_engine.py` keeps the same channel classification.
- [ ] Run the targeted semantic and vector-index tests and confirm they pass.

### Task 3: Preserve the audit API contract

**Files:**
- Modify: `src/test_rule_engine_mvp.py`
- Modify: `src/test_audit_api_auth.py`
- Modify only if required: `src/rule_engine.py`

- [ ] Add a contract regression test using a scenario-enabled rule and assert the existing top-level `code/msg/data`, routing, Chinese output fields, and `matched_rules` parent-rule cardinality.
- [ ] Run the contract test and confirm it fails before the scenario implementation is complete.
- [ ] Make only the minimal internal adjustment required; do not add required response fields or change existing types/enums.
- [ ] Run the API and MVP tests and confirm the public contract remains unchanged.

### Task 4: Rewrite the Advertising Law JSON in dual format

**Files:**
- Modify: `jsonbase/20260623_中华人民共和国广告法_通用规则_v1.json`
- Modify: `schema/20260628_三赛道广告合规规则schema_v5.json`

- [ ] Preserve every existing parent `recall.vector_text` and add `semantic_scenarios` only to selected open-ended content rules.
- [ ] Split the over-broad Article 9 asset into parent rules whose legal meanings are independently recallable, while retaining stable complete rule objects and unique `rule_id`/`rule_uid` values.
- [ ] Add schema documentation for `semantic_scenarios`, `scenario_id`, `vector_text`, and optional `enabled`.
- [ ] Validate that every scenario ID is unique within its parent and every scenario text is non-empty.

### Task 5: Rebuild and verify

**Files:**
- Regenerate: `vectorbase/rule_vector_index.json`
- Verify: `schema/audit_response_schema_v0.1.json`

- [ ] Rebuild the cached vector index with the existing builder.
- [ ] Run the full rule-engine unittest suite.
- [ ] Run the baseline evaluation.
- [ ] Run a focused audit for “我们一降价，你还不是像狗一样跑过来” and confirm the good-customs parent rule is recalled once.
- [ ] Compare the final response keys and value types with the existing audit response schema.
