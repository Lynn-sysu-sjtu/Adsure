# Rule Governance and Structured Subsumption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interface-compatible rule-engine pipeline that enforces globally unique rule IDs, collapses semantically equivalent rules, and exposes only DeepSeek-confirmed violations or fact-verification requirements in `matched_rules`.

**Architecture:** Keep the three recall paths unchanged, then insert two deterministic layers before and after the existing final DeepSeek call. Before the call, `candidate_governance.py` validates IDs, collapses legal-issue groups, applies platform and authority selection, and limits the pool. After the call, `subsumption.py` validates one judgment per candidate, filters `not_applicable`, and drives risk, routing, and opinion synthesis. `/audit` and Feishu field names remain unchanged.

**Tech Stack:** Python 3.12, `unittest`, JSON rule assets, existing DeepSeek client, existing Zhipu embedding client, FastAPI `/audit`, systemd deployment.

---

## File map

New focused modules and assets:

```text
rule_engine/src/rule_asset_validator.py       Rule/schema/reference validation
rule_engine/src/rule_id_migration.py          Source-aware and idempotent ID migration
rule_engine/src/legal_issue_groups.py         Group asset loading and authority/platform selection
rule_engine/src/build_legal_issue_groups.py   Offline vector candidate generation and report output
rule_engine/src/candidate_governance.py        Runtime candidate collapse, quotas, and ordering
rule_engine/src/subsumption.py                 LLM judgment contract validation and final rule filtering
rule_engine/assets/legal_issue_groups.json     Reviewed legal-issue groups
rule_engine/migrations/rule_id_migrations.json Explicit source-file-aware ID migrations
```

Existing modules modified:

```text
rule_engine/src/kg_rule_store.py
rule_engine/src/rule_engine.py
rule_engine/src/llm_judgment.py
rule_engine/src/run_engine_baseline_eval.py
rule_engine/schema/audit_response_schema_v0.1.json
rule_engine/test_cases/rule_engine_cases_v0.1.json
rule_engine/vectorbase/rule_vector_index.json
```

## Task 1: Freeze the current baseline and add asset-validation tests

**Files:**
- Create: `rule_engine/src/test_rule_asset_validator.py`
- Create: `rule_engine/src/rule_asset_validator.py`
- Modify: `rule_engine/src/kg_rule_store.py:55-110`

- [ ] **Step 1: Run and record the pre-change suite**

Run:

```powershell
cd "D:\G-Vibe coding\广告合规审查智能体\Adsure\rule_engine\src"
py -3 -m unittest discover -s .
```

Expected: `Ran 109 tests` and `OK` before new tests are added.

- [ ] **Step 2: Write failing duplicate-ID and orphan-reference tests**

Create tests using temporary directories so production assets are not modified:

```python
class RuleAssetValidatorTests(unittest.TestCase):
    def test_duplicate_rule_ids_report_source_files(self):
        report = validate_rule_assets(
            rules=[
                {"rule_id": "DUP-001", "title": "规则A", "_source_file": "a.json"},
                {"rule_id": "DUP-001", "title": "规则B", "_source_file": "b.json"},
            ],
            vector_rule_ids=set(),
            expected_rule_ids=set(),
            group_rule_ids=set(),
        )
        self.assertEqual(1, len(report["duplicate_rule_ids"]))
        self.assertEqual(["a.json", "b.json"], report["duplicate_rule_ids"][0]["source_files"])

    def test_orphan_vector_ids_are_reported(self):
        report = validate_rule_assets(
            rules=[{"rule_id": "RULE-001", "title": "规则", "_source_file": "a.json"}],
            vector_rule_ids={"RULE-404"},
            expected_rule_ids=set(),
            group_rule_ids=set(),
        )
        self.assertEqual(["RULE-404"], report["orphan_vector_rule_ids"])
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
py -3 -m unittest test_rule_asset_validator.py
```

Expected: import failure for `rule_asset_validator`.

- [ ] **Step 4: Implement the minimal validator**

Create public functions:

```python
def validate_rule_assets(rules, vector_rule_ids=None, expected_rule_ids=None, group_rule_ids=None):
    by_id = {}
    for rule in rules:
        rule_id = str(rule.get("rule_id") or "").strip()
        if rule_id:
            by_id.setdefault(rule_id, []).append(rule)
    duplicates = []
    for rule_id, members in sorted(by_id.items()):
        if len(members) > 1:
            duplicates.append({
                "rule_id": rule_id,
                "source_files": sorted(str(item.get("_source_file") or "") for item in members),
                "titles": sorted({str(item.get("title") or "") for item in members}),
            })
    known = set(by_id)
    return {
        "duplicate_rule_ids": duplicates,
        "orphan_vector_rule_ids": sorted(set(vector_rule_ids or ()) - known),
        "orphan_test_expected_rule_ids": sorted(set(expected_rule_ids or ()) - known),
        "orphan_group_rule_ids": sorted(set(group_rule_ids or ()) - known),
    }

def assert_valid_rule_assets(report):
    failures = {key: value for key, value in report.items() if value}
    if failures:
        raise ValueError("Invalid rule assets: " + json.dumps(failures, ensure_ascii=False))
```

Add optional validation to `load_rule_library(base_dir, validate_assets=False)` without enabling it in production yet.

- [ ] **Step 5: Run validator tests and full regression suite**

Run:

```powershell
py -3 -m unittest test_rule_asset_validator.py
py -3 -m unittest discover -s .
```

Expected: new tests pass; all existing tests remain green.

- [ ] **Step 6: Commit Task 1**

```powershell
git add rule_engine/src/rule_asset_validator.py rule_engine/src/test_rule_asset_validator.py rule_engine/src/kg_rule_store.py
git commit -m "test(rule-engine): add rule asset validation foundation"
```

## Task 2: Build source-aware Rule ID migration and eliminate collisions

**Files:**
- Create: `rule_engine/src/test_rule_id_migration.py`
- Create: `rule_engine/src/rule_id_migration.py`
- Create: `rule_engine/migrations/rule_id_migrations.json`
- Modify: conflicting files under `rule_engine/jsonbase/`
- Modify: `rule_engine/test_cases/rule_engine_cases_v0.1.json`
- Modify: `rule_engine/vectorbase/rule_vector_index.json`

- [ ] **Step 1: Write failing migration tests**

Test source-aware selection and idempotence:

```python
def test_migration_changes_only_matching_source_and_old_id(self):
    rules = [
        {"rule_id": "DUP-001", "_source_file": "a.json"},
        {"rule_id": "DUP-001", "_source_file": "b.json"},
    ]
    migrations = [{"source_file": "b.json", "old_rule_id": "DUP-001", "new_rule_id": "B-001"}]
    changed = apply_rule_id_migrations(rules, migrations)
    self.assertEqual(["DUP-001", "B-001"], [rule["rule_id"] for rule in changed])

def test_migration_is_idempotent(self):
    first = apply_rule_id_migrations(self.rules, self.migrations)
    second = apply_rule_id_migrations(first, self.migrations)
    self.assertEqual(first, second)
```

- [ ] **Step 2: Run migration tests and verify RED**

```powershell
py -3 -m unittest test_rule_id_migration.py
```

Expected: import failure for `rule_id_migration`.

- [ ] **Step 3: Implement migration primitives**

```python
def migration_key(item):
    return str(item["source_file"]), str(item["old_rule_id"])

def apply_rule_id_migrations(rules, migrations):
    mapping = {migration_key(item): str(item["new_rule_id"]) for item in migrations}
    output = copy.deepcopy(rules)
    for rule in output:
        key = (str(rule.get("_source_file") or ""), str(rule.get("rule_id") or ""))
        target = mapping.get(key)
        if target and rule.get("rule_id") != target:
            rule["rule_id"] = target
    return output
```

Add functions to update vector-index entries and test-case expected IDs using the same source-qualified migration manifest. Refuse any manifest whose new IDs collide.

- [ ] **Step 4: Generate a dry-run collision report**

Run:

```powershell
py -3 .\rule_id_migration.py --base-dir .. --manifest ..\migrations\rule_id_migrations.json --dry-run
```

Expected: report lists every current collision, affected source file, old ID, proposed new ID, vector references, and baseline references; no files change.

- [ ] **Step 5: Review and complete the explicit migration manifest**

Use descriptive IDs derived from platform and legal issue, not numeric suffixes that preserve ambiguity. The manifest must cover every duplicate occurrence except the intentionally retained canonical occurrence.

- [ ] **Step 6: Apply migrations and rebuild the vector index**

Run:

```powershell
py -3 .\rule_id_migration.py --base-dir .. --manifest ..\migrations\rule_id_migrations.json --apply
py -3 .\build_rule_vector_index.py
```

Expected: migration summary reports changed files; vector index builds without orphan IDs.

- [ ] **Step 7: Verify uniqueness and regression tests**

```powershell
py -3 -m unittest test_rule_asset_validator.py test_rule_id_migration.py test_rule_vector_index.py
py -3 -m unittest discover -s .
```

Expected: duplicate and orphan counts are zero; all tests pass.

- [ ] **Step 8: Commit Task 2**

Stage only the manifest, migration code/tests, modified rule assets, test cases, and rebuilt vector index. Exclude reports.

```powershell
git commit -m "fix(rule-assets): migrate duplicate rule identifiers"
```

## Task 3: Add legal-issue group asset validation and selection

**Files:**
- Create: `rule_engine/assets/legal_issue_groups.json`
- Create: `rule_engine/src/legal_issue_groups.py`
- Create: `rule_engine/src/test_legal_issue_group_assets.py`
- Create: `rule_engine/src/test_legal_issue_rule_selection.py`

- [ ] **Step 1: Write failing group-asset tests**

```python
def test_group_members_must_reference_existing_rules(self):
    with self.assertRaisesRegex(ValueError, "UNKNOWN-001"):
        validate_legal_issue_groups(
            {"groups": [{"issue_group_id": "g1", "member_rule_ids": ["UNKNOWN-001"]}]},
            known_rule_ids={"RULE-001"},
        )

def test_content_and_fact_rules_cannot_share_a_group(self):
    with self.assertRaisesRegex(ValueError, "trigger_layer"):
        validate_group_trigger_layers(
            [self.content_rule, self.fact_rule]
        )
```

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_legal_issue_group_assets.py test_legal_issue_rule_selection.py
```

- [ ] **Step 3: Implement group loading and validation**

```python
def load_legal_issue_groups(base_dir):
    path = Path(base_dir) / "assets" / "legal_issue_groups.json"
    if not path.exists():
        return {"groups": []}
    return json.loads(path.read_text(encoding="utf-8-sig"))

def group_index(asset):
    return {
        rule_id: group
        for group in asset.get("groups", [])
        for rule_id in group.get("member_rule_ids", [])
    }
```

Validate unique group IDs, valid member IDs, no duplicate membership, one trigger layer per group, and valid selection policy values.

- [ ] **Step 4: Write authority/platform selection tests**

```python
def test_selects_highest_authority_and_current_platform(self):
    selected, supporting = select_group_representatives(
        rules=[self.department_rule, self.xhs_rule, self.douyin_rule],
        platform="小红书",
    )
    self.assertEqual(["DEPT-001", "XHS-001"], [rule["rule_id"] for rule in selected])
    self.assertEqual(["DY-001"], supporting)

def test_missing_platform_keeps_only_primary_rule(self):
    selected, supporting = select_group_representatives(
        rules=[self.department_rule, self.xhs_rule],
        platform="",
    )
    self.assertEqual(["DEPT-001"], [rule["rule_id"] for rule in selected])
```

- [ ] **Step 5: Implement deterministic selection**

Use a centralized authority rank map and platform normalization. Return selected rules plus supporting IDs; never mutate input rules.

- [ ] **Step 6: Seed the first reviewed groups**

At minimum include the known cosmetic special-efficacy/filing group and any other duplicate legal issues found during the Rule ID migration report. Every group must pass asset validation.

- [ ] **Step 7: Run tests and commit**

```powershell
py -3 -m unittest test_legal_issue_group_assets.py test_legal_issue_rule_selection.py
git commit -m "feat(rule-engine): add legal issue group selection"
```

## Task 4: Build the offline semantic grouping report

**Files:**
- Create: `rule_engine/src/build_legal_issue_groups.py`
- Create: `rule_engine/src/test_semantic_rule_clustering.py`
- Create: `rule_engine/reports/legal_issue_groups/.gitkeep`

- [ ] **Step 1: Write failing clustering tests**

```python
def test_similarity_candidates_respect_trigger_layer(self):
    pairs = candidate_pairs(
        [self.content_rule, self.similar_content_rule, self.fact_rule],
        embeddings=self.embeddings,
        threshold=0.85,
    )
    self.assertEqual([("CONTENT-1", "CONTENT-2")], [(p["left_id"], p["right_id"]) for p in pairs])

def test_candidate_report_does_not_modify_group_asset(self):
    build_candidate_report(self.rules, self.embeddings, self.output_path)
    self.assertFalse(self.group_asset_path.exists())
```

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_semantic_rule_clustering.py
```

- [ ] **Step 3: Implement cosine candidate generation**

Reuse cached vectors from `vectorbase/rule_vector_index.json`. Generate pairs only when industry and trigger layer are compatible. Report similarity, titles, sources, authority levels, platforms, and proposed issue label. Do not auto-write approved groups.

- [ ] **Step 4: Generate and review the first report**

```powershell
py -3 .\build_legal_issue_groups.py --base-dir .. --threshold 0.85
```

Expected: timestamped JSON and Markdown reports under `reports/legal_issue_groups/`; reviewed decisions are manually copied into `assets/legal_issue_groups.json`.

- [ ] **Step 5: Run asset validation after review and commit code/approved asset only**

Do not commit generated reports.

```powershell
py -3 -m unittest test_semantic_rule_clustering.py test_legal_issue_group_assets.py
git commit -m "feat(rule-engine): add offline semantic rule grouping"
```

## Task 5: Insert legal-issue collapse and quotas into the judgment pool

**Files:**
- Create: `rule_engine/src/candidate_governance.py`
- Create: `rule_engine/src/test_candidate_pool_governance.py`
- Modify: `rule_engine/src/rule_engine.py:295-347,770-790`
- Modify: `rule_engine/src/test_recall_merge_and_judgment_pool.py`

- [ ] **Step 1: Write failing governance tests**

```python
def test_govern_pool_keeps_primary_current_platform_and_open_rule(self):
    result = govern_candidates(
        recalled=self.recalled,
        request={"context": {"platforms": ["小红书"]}},
        group_asset=self.groups,
        limit=8,
    )
    ids = [rule["rule_id"] for rule, _ in result]
    self.assertIn("DEPT-COSM-001", ids)
    self.assertIn("XHS-COSM-001", ids)
    self.assertIn("GEN-GOOD-CUSTOMS-001", ids)
    self.assertNotIn("DY-COSM-001", ids)

def test_fact_rules_cannot_consume_more_than_three_slots(self):
    result = govern_candidates(self.many_fact_rules, self.request, self.groups, limit=8)
    self.assertLessEqual(sum(rule["recall"]["trigger_layer"] == "fact" for rule, _ in result), 3)
```

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_candidate_pool_governance.py
```

- [ ] **Step 3: Implement governance as a pure function**

```python
def govern_candidates(recalled, request, group_asset, limit=8):
    merged = merge_parent_candidates(recalled)
    collapsed = collapse_issue_groups(merged, request, group_asset)
    ranked = sorted(collapsed, key=candidate_sort_key)
    return apply_candidate_quotas(
        ranked,
        limit=limit,
        max_fact=3,
        max_platform=2,
        max_per_group=2,
        reserve_open_content=1,
    )
```

Preserve all recall channels and hit evidence on selected parents. Attach `supporting_rule_ids` only to internal candidate dictionaries.

- [ ] **Step 4: Integrate into `audit` without changing response fields**

Keep full raw recall internal. Replace `_select_judgment_recalled(recalled)` with governed candidates loaded from `assets/legal_issue_groups.json`.

- [ ] **Step 5: Run focused and full tests**

```powershell
py -3 -m unittest test_candidate_pool_governance.py test_recall_merge_and_judgment_pool.py test_three_way_recall_orchestration.py
py -3 -m unittest discover -s .
```

- [ ] **Step 6: Commit Task 5**

```powershell
git commit -m "feat(rule-engine): govern legal issue candidates"
```

## Task 6: Define the structured DeepSeek subsumption contract

**Files:**
- Create: `rule_engine/src/test_subsumption_contract.py`
- Modify: `rule_engine/src/llm_judgment.py:103-256`
- Modify: `rule_engine/src/test_llm_judgment_mock.py`
- Modify: `rule_engine/src/test_rule_engine_llm_payload.py`

- [ ] **Step 1: Write failing prompt-contract tests**

```python
def test_prompt_requires_one_judgment_per_candidate(self):
    messages = build_judgment_messages(self.context, self.rules, mode="strict")
    payload = json.loads(messages[-1]["content"])
    contract = payload["output_contract"]
    self.assertEqual(
        "confirmed_violation | needs_fact_verification | not_applicable",
        contract["rule_judgments"][0]["applicability_status"],
    )
    self.assertTrue(payload["judgment_policy"]["require_every_candidate_once"])
```

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_subsumption_contract.py test_rule_engine_llm_payload.py
```

- [ ] **Step 3: Replace the LLM output contract**

Require `rule_judgments` with the exact fields from the design. Instruct the model that keyword presence proves relevance only, missing facts cannot become violations, and direct content violations outrank supplemental fact checks.

- [ ] **Step 4: Update mock judgment output**

The deterministic mock must return one judgment per candidate. Content rules default to `confirmed_violation` only in tests that explicitly supply violation evidence; fact rules return `needs_fact_verification` with non-empty missing facts; irrelevant test fixtures explicitly return `not_applicable`.

- [ ] **Step 5: Run judgment tests and commit**

```powershell
py -3 -m unittest test_subsumption_contract.py test_llm_judgment_mock.py test_rule_engine_llm_payload.py
git commit -m "feat(rule-engine): define structured subsumption contract"
```

## Task 7: Validate subsumption and build final matched rules

**Files:**
- Create: `rule_engine/src/subsumption.py`
- Create: `rule_engine/src/test_subsumption_filter.py`
- Modify: `rule_engine/src/llm_judgment.py:196-256`

- [ ] **Step 1: Write failing parser and evidence tests**

```python
def test_filters_not_applicable_but_keeps_fact_verification(self):
    result = validate_subsumption_result(
        candidate_rules=self.candidates,
        raw_judgments=self.judgments,
        material_text=self.material,
    )
    self.assertEqual(
        ["GEN-GOOD-CUSTOMS-001", "COSM-002"],
        [item["rule_id"] for item in result.final_rules],
    )

def test_confirmed_evidence_must_be_continuous_original_text(self):
    self.judgments[0]["material_evidence"] = "消费者受到动物化贬损"
    with self.assertRaises(SubsumptionValidationError):
        validate_subsumption_result(self.candidates, self.judgments, self.material)
```

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_subsumption_filter.py
```

- [ ] **Step 3: Implement strict validation**

```python
ALLOWED_STATUSES = {"confirmed_violation", "needs_fact_verification", "not_applicable"}

@dataclass
class ValidatedSubsumption:
    final_rules: list
    rejected_rules: list
    judgments: list

def validate_subsumption_result(candidate_rules, raw_judgments, material_text):
    candidate_by_id = {rule["rule_id"]: rule for rule in candidate_rules}
    returned_ids = [str(item.get("rule_id") or "") for item in raw_judgments]
    if len(returned_ids) != len(candidate_by_id) or set(returned_ids) != set(candidate_by_id):
        raise SubsumptionValidationError("Every candidate must be judged exactly once")
    # Validate status, evidence, and missing_facts; enrich final copies without mutating candidates.
```

Use normalized Unicode punctuation for matching but require the evidence text to remain a contiguous substring of normalized material.

- [ ] **Step 4: Add tests for outside IDs, duplicates, missing facts, illegal status, and wrong types**

Every structural failure raises `SubsumptionValidationError`; do not partially trust a malformed response.

- [ ] **Step 5: Run tests and commit**

```powershell
py -3 -m unittest test_subsumption_filter.py test_subsumption_contract.py
git commit -m "feat(rule-engine): validate structured subsumption results"
```

## Task 8: Integrate final-rule filtering and conservative fallback into `/audit`

**Files:**
- Create: `rule_engine/src/test_rule_subsumption_cases.py`
- Create: `rule_engine/src/test_subsumption_failure_fallback.py`
- Modify: `rule_engine/src/rule_engine.py:762-858`
- Modify: `rule_engine/src/test_audit_contract_semantic_scenarios.py`

- [ ] **Step 1: Write the core failing case**

Mock recall and DeepSeek so the candidate pool contains good customs, cosmetic filing, false advertising, minors, and data citation rules. Return statuses:

```python
judgments = [
    judgment("GEN-GOOD-CUSTOMS-001", "confirmed_violation", "像狗一样跑过来"),
    judgment("COSM-002", "needs_fact_verification", "美白精华", missing_facts=["产品注册备案类别"]),
    judgment("COSM-FALSE-004", "not_applicable", "美白精华"),
    judgment("IAM-MINOR-001", "not_applicable", ""),
    judgment("XHS-COSM-DATA-003", "not_applicable", ""),
]
```

Assert only the first two rules appear in `data.matched_rules`, risk is high, routing is legal, and the opinion starts with violation rather than supplemental materials.

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_rule_subsumption_cases.py
```

- [ ] **Step 3: Integrate validation into `audit`**

Change data flow to:

```python
candidate_rules = [_matched_rule(rule, hits) for rule, hits in governed_recalled]
llm_judgment = _judge_with_config(context_package, candidate_rules)
validated = validate_subsumption_result(
    candidate_rules,
    llm_judgment["rule_judgments"],
    context_package.get("material_text") or "",
)
matched_rules = validated.final_rules
```

Do not expose raw candidates in `/audit`.

- [ ] **Step 4: Write failure-fallback tests**

Cover timeout, network exception, non-JSON, missing candidate, duplicate candidate, outside ID, and invalid evidence. Each must return:

```text
code=0, matched_rules=[], risk=中, routing=法务, opinion contains 人工复核
```

- [ ] **Step 5: Implement one conservative fallback builder**

```python
def _subsumption_fallback_response(request, context_package, audit_timestamp, reason_code):
    opinion = "意见类型：人工复核\n\nAI规则涵摄未能完成，本次不展示未经确认的候选规则，请法务结合物料原文进行人工审核。"
    return {
        "code": 0,
        "msg": "ok",
        "data": {
            "tenant_id": request.get("tenant_id", "adsure_demo"),
            "request_id": request.get("request_id"),
            "resolved_mode": "标准",
            "mode_reason": STANDARD_MODE_REASON,
            "预审_风险等级": "中",
            "预审_命中要点": "AI规则涵摄未完成，需人工复核。",
            "预审_修改建议": "请提交法务人工复核。",
            "预审_时间": audit_timestamp,
            "审核_审核意见": opinion,
            "审核_关键实体抽取": "",
            "审核_高风险词命中": "无",
            "审核_平台规则预检": "本次涵摄未完成，未形成平台规则结论。",
            "审核_备案核查结果": "本次涵摄未完成，请人工核查备案和证明材料。",
            "审核_推荐违规类型": [],
            "审核_推荐风险等级": "中",
            "risk_assessment": {
                "rule_engine_risk_level": "无明显风险",
                "llm_risk_level": "中",
                "final_risk_level": "中",
                "risk_disagreement": True,
                "risk_disagreement_reason": "AI规则涵摄未完成。",
                "final_risk_source": "subsumption_fallback",
                "final_risk_reason": reason_code,
            },
            "matched_rules": [],
            "semantic_recall": {"enabled": True, "matched_rule_ids": []},
            "rule_judgments": [],
            "llm_judgment": {
                "engine": "subsumption_fallback",
                "opinion_type": "人工复核",
                "overall_risk_level": "中",
                "rule_judgments": [],
                "audit_opinion": opinion,
            },
            "context_package": context_package,
            "routing": "法务",
            "审核_审核时间": audit_timestamp,
            "audit_time": audit_timestamp,
        },
    }
```

Populate all existing contract fields using the same request IDs and timestamps as the normal response. Log only reason code, request ID, elapsed time, and candidate IDs.

- [ ] **Step 6: Run contract and fallback tests**

```powershell
py -3 -m unittest test_rule_subsumption_cases.py test_subsumption_failure_fallback.py test_audit_contract_semantic_scenarios.py test_audit_api_auth.py
```

- [ ] **Step 7: Commit Task 8**

```powershell
git commit -m "feat(rule-engine): filter final rules through subsumption"
```

## Task 9: Recompute risk, routing, and opinion from confirmed rules

**Files:**
- Create: `rule_engine/src/test_confirmed_rule_risk_synthesis.py`
- Create: `rule_engine/src/test_audit_opinion_priority.py`
- Create: `rule_engine/src/test_confirmed_rule_routing.py`
- Modify: `rule_engine/src/rule_engine.py:562-759,790-855`

- [ ] **Step 1: Write failing synthesis tests**

```python
def test_confirmed_violation_outranks_fact_verification(self):
    result = synthesize_confirmed_outcome(
        [self.good_customs_confirmed, self.cosmetic_fact],
        llm_risk="高",
    )
    self.assertEqual("违规修改", result.opinion_type)
    self.assertEqual("高", result.risk)
    self.assertEqual("法务", result.routing)

def test_raw_high_risk_candidate_does_not_create_medium_floor(self):
    result = synthesize_confirmed_outcome([], llm_risk="无明显风险")
    self.assertEqual("无明显风险", result.risk)
```

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_confirmed_rule_risk_synthesis.py test_audit_opinion_priority.py test_confirmed_rule_routing.py
```

- [ ] **Step 3: Implement deterministic outcome helpers**

Create helpers that partition final rules by applicability status, compute risk only from final rules, route only from final rules, and render sections in this order: opinion type, core confirmed risks, supplemental fact checks, confirmed rules, fact-verification rules, legal basis, revision advice.

- [ ] **Step 4: Remove raw fact-advice precedence**

Replace `_compose_audit_opinion(fact_advice, ...)` with a function that receives confirmed and fact-verification partitions. `预审_修改建议`, `审核_备案核查结果`, recommended violation types, and high-risk-hit summary must also use final rules.

- [ ] **Step 5: Run focused and full tests**

```powershell
py -3 -m unittest test_confirmed_rule_risk_synthesis.py test_audit_opinion_priority.py test_confirmed_rule_routing.py test_risk_assessment_dual_track.py
py -3 -m unittest discover -s .
```

- [ ] **Step 6: Commit Task 9**

```powershell
git commit -m "feat(rule-engine): synthesize outcomes from confirmed rules"
```

## Task 10: Extend the response schema without breaking Feishu

**Files:**
- Modify: `rule_engine/schema/audit_response_schema_v0.1.json:107-151`
- Create: `rule_engine/src/test_audit_contract_subsumption.py`
- Read-only verify: `feishu_state_machine/predictor.py:397-422`

- [ ] **Step 1: Write a failing schema-contract test**

Validate that each final rule preserves old required fields and accepts the new optional fields. Assert the top-level response key set and Feishu field names remain unchanged.

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_audit_contract_subsumption.py
```

- [ ] **Step 3: Add optional schema fields**

Add schemas for:

```json
{
  "applicability_status": {"enum": ["confirmed_violation", "needs_fact_verification"]},
  "material_evidence": {"type": "string"},
  "satisfied_elements": {"type": "array", "items": {"type": "string"}},
  "unsatisfied_elements": {"type": "array", "items": {"type": "string"}},
  "missing_facts": {"type": "array", "items": {"type": "string"}},
  "applicability_reason": {"type": "string"},
  "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1}
}
```

Do not add them to the required list.

- [ ] **Step 4: Run contract tests and commit**

```powershell
py -3 -m unittest test_audit_contract_subsumption.py test_audit_contract_semantic_scenarios.py
git commit -m "docs(rule-engine): extend matched rule applicability schema"
```

## Task 11: Split baseline recall and confirmed-match metrics

**Files:**
- Modify: `rule_engine/src/run_engine_baseline_eval.py:78-395`
- Modify: `rule_engine/src/test_engine_baseline_eval.py`
- Modify: `rule_engine/test_cases/rule_engine_cases_v0.1.json`

- [ ] **Step 1: Write failing evaluator tests**

```python
def test_evaluator_separates_candidate_recall_from_confirmed_match(self):
    report = evaluate_response(self.case, self.response)
    self.assertEqual(["GEN-GOOD-CUSTOMS-001", "COSM-FALSE-004"], report["candidate_rule_ids"])
    self.assertEqual(["GEN-GOOD-CUSTOMS-001"], report["confirmed_rule_ids"])
    self.assertEqual(["COSM-002"], report["fact_verification_rule_ids"])
```

- [ ] **Step 2: Verify RED**

```powershell
py -3 -m unittest test_engine_baseline_eval.py
```

- [ ] **Step 3: Add internal diagnostics for the evaluator**

Do not expose candidates through `/audit`. Add an internal audit diagnostics function or evaluator hook that captures governed candidate IDs before subsumption. `evaluate_case` calls this internal path; production `/audit` still returns the existing contract.

- [ ] **Step 4: Add metrics**

Report candidate recall, confirmed recall, confirmed precision, fact-verification accuracy, not-applicable filtering accuracy, average candidate count, average final-rule count, compression ratio, failure fallback count, and latency percentiles.

- [ ] **Step 5: Add the seven end-to-end cases**

Extend the case JSON with the good-customs-plus-whitening case, plain whitening description, explicit exaggerated effect, minors-media case, data-citation case, all-not-applicable case, and fallback case. Include expected candidate IDs, confirmed IDs, fact-verification IDs, risk, routing, and opinion type.

- [ ] **Step 6: Run evaluator tests and mock baseline**

```powershell
py -3 -m unittest test_engine_baseline_eval.py
$env:ADSURE_LLM_BACKEND='mock'
$env:ADSURE_LLM_MODE='strict'
$env:ADSURE_SEMANTIC_BACKEND='zhipu'
py -3 .\run_engine_baseline_eval.py
```

Expected: zero evaluator errors; report contains separate candidate and confirmed metrics.

- [ ] **Step 7: Commit Task 11**

```powershell
git commit -m "test(rule-engine): separate recall and subsumption metrics"
```

## Task 12: Full verification, real baseline, and deployment readiness

**Files:**
- Modify if required by verified behavior only: `rule_engine/docs/2026-07-19-three-way-recall-implementation-plan.md`
- Generate but do not commit: `rule_engine/test_reports/*.json`

- [ ] **Step 1: Run the complete test suite**

```powershell
cd "D:\G-Vibe coding\广告合规审查智能体\Adsure\rule_engine\src"
py -3 -m unittest discover -s .
```

Expected: approximately 170-200 tests, zero failures and zero errors.

- [ ] **Step 2: Run asset validation as a deployment gate**

```powershell
py -3 .\rule_asset_validator.py --base-dir .. --strict
```

Expected:

```text
duplicate_rule_id_count=0
orphan_vector_rule_id_count=0
orphan_test_expected_rule_id_count=0
orphan_group_rule_id_count=0
```

- [ ] **Step 3: Run the first real DeepSeek + Zhipu baseline**

```powershell
$env:ADSURE_LLM_BACKEND='deepseek'
$env:ADSURE_LLM_MODE='strict'
$env:ADSURE_SEMANTIC_BACKEND='zhipu'
$env:ADSURE_SEMANTIC_THRESHOLD='0.50'
$env:ADSURE_FALLBACK_SEMANTIC_THRESHOLD='0.55'
$env:ADSURE_CATALOG_RECALL_ENABLED='true'
$env:ADSURE_CATALOG_LLM_BACKEND='deepseek'
$env:ADSURE_CATALOG_RECALL_LIMIT='1'
$env:ADSURE_JUDGMENT_POOL_LIMIT='8'
py -3 .\run_engine_baseline_eval.py
```

Expected: no engine errors; target candidate recall does not regress; good-customs case has confirmed high risk and legal routing; irrelevant false/minor/data rules are filtered.

- [ ] **Step 4: Calibrate only the prompt or deterministic policies shown by evidence**

If metrics miss targets, change one variable at a time, add a failing regression test for the observed case, implement the smallest correction, rerun focused tests, then rerun the real baseline. Do not edit rule assets and prompts simultaneously for the same failure.

- [ ] **Step 5: Run the second real baseline**

Use the same environment and command. Compare reports for candidate recall, confirmed precision, filter accuracy, average final rules, average elapsed time, P50, and P95.

Acceptance targets:

```text
Rule ID conflicts: 0
/audit contract: 100%
Candidate recall: no regression from current 24/24 target
Irrelevant-rule filter accuracy: at least 80%
Core-risk ordering for target cases: 100%
Average judgment pool: at most 8
Average displayed final rules: at most 4
```

- [ ] **Step 6: Perform a local `/audit` smoke test**

Use the exact material:

```text
我们的美白精华一降价，你还不是像狗一样跑过来。
```

Expected final rules: good customs as `confirmed_violation`, one cosmetic filing rule as `needs_fact_verification`; no false-advertising, minors, or data-citation final rules; high risk; legal routing.

- [ ] **Step 7: Commit final verified adjustments**

Stage only source, tests, rule assets, approved grouping asset, migration manifest, schema, test cases, vector index, and documentation. Exclude generated reports.

```powershell
git commit -m "feat(rule-engine): complete governed subsumption pipeline"
```

- [ ] **Step 8: Merge, push, and deploy using the existing safe release flow**

After merged-branch tests pass, push `dev`, generate a `git archive` release from the exact commit, upload to an isolated cloud release directory, run the full cloud test suite, back up `/opt/adsure_rule_engine/current`, switch atomically, restart `adsure-rule-engine.service`, call `/health`, and execute the target `/audit` smoke test. Verify local, GitHub, and cloud commit markers are identical.

## Final verification checklist

- [ ] Full rule IDs are unique.
- [ ] No vector, case, or group orphan references exist.
- [ ] Current-platform and authority selection tests pass.
- [ ] Candidate pool never exceeds eight.
- [ ] Every candidate receives exactly one DeepSeek judgment.
- [ ] `not_applicable` never appears in final `matched_rules`.
- [ ] `needs_fact_verification` remains visible with missing facts.
- [ ] Confirmed direct violations outrank supplemental fact checks.
- [ ] LLM failures return `code=0`, medium risk, legal routing, empty rules, and manual-review text.
- [ ] `/audit` and Feishu contracts remain compatible.
- [ ] Real baseline and cloud smoke tests satisfy acceptance targets.

