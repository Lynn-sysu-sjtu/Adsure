# Dual Rule Identity Migration Implementation Plan

> **For agentic workers:** This plan replaces Task 2 of `2026-07-19-rule-governance-and-subsumption.md`. Later tasks must use `rule_uid` as the internal identity while preserving `rule_id` externally.

**Goal:** Assign every rule a deterministic persisted `rule_uid` and migrate internal references without renaming legacy `rule_id` values.

**Architecture:** A source-aware UID generator hashes stable rule provenance and legal content only for rules missing a UID. The validator treats UID uniqueness as the deployment gate while legacy ID collisions remain reportable. Runtime, vector, grouping, and subsumption code use UID; `/audit.rule_id` remains compatible.

---

## Task 2A: Extend validation for dual identity

**Files:**
- Modify: `rule_engine/src/rule_asset_validator.py`
- Modify: `rule_engine/src/test_rule_asset_validator.py`

- [ ] Add failing tests for empty and duplicate `rule_uid`, and for legacy duplicate IDs remaining reportable without being the strict UID gate.
- [ ] Verify RED.
- [ ] Add `empty_rule_uids`, `duplicate_rule_uids`, `orphan_vector_rule_uids`, and `orphan_group_rule_uids` to the report.
- [ ] Add `assert_valid_rule_uids(report)` that fails only on UID identity/reference problems.
- [ ] Run focused and full tests.

## Task 2B: Generate and persist deterministic UIDs

**Files:**
- Create: `rule_engine/src/rule_uid_migration.py`
- Create: `rule_engine/src/test_rule_uid_migration.py`
- Modify: all rule JSON files containing rules without `rule_uid`

- [ ] Write failing tests for deterministic generation, idempotence, no replacement of existing UID, source-sensitive uniqueness, and collision rejection.
- [ ] Verify RED.
- [ ] Implement `rule_uid_seed(rule)` using source file, legacy ID, title and normalized legal basis.
- [ ] Implement `generate_rule_uid(rule)` as `RU-` plus the first 20 uppercase SHA-256 hex characters.
- [ ] Implement dry-run and apply modes; write only missing UIDs.
- [ ] Run dry-run and persist a report outside version control.
- [ ] Apply to all formal rule JSON assets.
- [ ] Verify 892 rules have 892 unique non-empty UIDs.

## Task 2C: Add UIDs to the vector index

**Files:**
- Modify: `rule_engine/src/rule_vector_index.py`
- Modify: `rule_engine/src/build_rule_vector_index.py`
- Modify: related vector-index tests
- Rebuild: `rule_engine/vectorbase/rule_vector_index.json`

- [ ] Write failing tests that every parent/scenario vector entry carries `rule_uid` and that duplicate legacy IDs remain distinguishable.
- [ ] Verify RED.
- [ ] Build index keys and cache lookup using `rule_uid` plus scenario ID.
- [ ] Preserve legacy `rule_id` as display metadata.
- [ ] Rebuild the index with the existing Zhipu embedding configuration.
- [ ] Verify no orphan vector UIDs and unchanged vector dimension.

## Task 2D: Switch runtime parent identity to UID

**Files:**
- Modify: `rule_engine/src/rule_engine.py`
- Modify: `rule_engine/src/semantic_recall.py`
- Modify: `rule_engine/src/catalog_rule_directory.py`
- Modify: recall and parent-dedup tests

- [ ] Write failing tests showing two rules with the same legacy ID but different UIDs do not merge.
- [ ] Verify RED.
- [ ] Add one helper `rule_identity(rule)` returning UID first and legacy ID only as migration fallback.
- [ ] Use the helper for parent merge, semantic cache matching and catalog identity.
- [ ] Include both UID and legacy ID in internal matched-rule dictionaries.
- [ ] Run all recall tests and full regression.

## Task 2E: Preserve external and baseline compatibility

**Files:**
- Modify: `rule_engine/schema/audit_response_schema_v0.1.json`
- Modify: `rule_engine/src/run_engine_baseline_eval.py`
- Modify: `rule_engine/test_cases/rule_engine_cases_v0.1.json` only where exact UID assertions are required

- [ ] Write failing contract tests that `rule_id` is unchanged and optional `rule_uid` is present.
- [ ] Add UID-aware baseline metrics while retaining legacy expected IDs.
- [ ] Confirm Feishu fields and top-level `/audit` structure remain unchanged.
- [ ] Run the complete test suite and commit the dual-ID migration.

## Acceptance

```text
all_rule_count = 892
non_empty_rule_uid_count = 892
unique_rule_uid_count = 892
duplicate_rule_uid_count = 0
duplicate legacy rule_id groups remain visible in reports
/audit rule_id compatibility remains unchanged
```

