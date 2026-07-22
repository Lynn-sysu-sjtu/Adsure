# Context Provenance and Industry Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass supplemental background into DeepSeek with explicit provenance, prevent the Feishu industry field from independently proving product legal identity, and preserve the public `/audit` contract.

**Architecture:** Keep keyword and semantic recall unchanged. Build a separate internal judgment context from the public context package, add explicit-industry-conflict signals, constrain DeepSeek through prompt policy, and apply a deterministic post-LLM guard before subsumption validation so model variation cannot confirm industry-specific rules solely from the industry label.

**Tech Stack:** Python 3, `unittest`, existing DeepSeek strict judgment pipeline, existing rule applicability metadata and subsumption validator.

---

## File Map

- Modify: `rule_engine/src/rule_engine.py`
  - Builds the private judgment context and passes it to DeepSeek without changing the public response context.
- Modify: `rule_engine/src/llm_judgment.py`
  - Adds provenance policy and deterministic industry-conflict guard.
- Create: `rule_engine/src/test_context_provenance_boundary.py`
  - Covers private context, conflict detection, guard behavior, prompt policy and public contract stability.
- Modify only if a new regression requires it: existing `/audit` contract tests.

## Task 1: Specify private judgment context and conflict detection

**Files:**
- Create: `rule_engine/src/test_context_provenance_boundary.py`
- Modify: `rule_engine/src/rule_engine.py`

- [ ] **Step 1: Write failing tests for the private context**

Add tests that construct a mapped request with:

```text
industry = 保健食品
content = 治疗肝癌、肺癌
supplemental_background = 产品为普通果汁饮品，非保健食品
product_category = 果汁饮品
```

Assertions:

```python
public_context = build_context_package(request)
judgment_context = build_judgment_context_package(request, public_context)

self.assertNotIn("supplemental_background", public_context)
self.assertEqual(
    "产品为普通果汁饮品，非保健食品",
    judgment_context["supplemental_background"],
)
self.assertEqual(
    "operator_supplied_unverified",
    judgment_context["context_provenance"]["supplemental_background"],
)
self.assertEqual(
    "recall_and_routing_label",
    judgment_context["context_provenance"]["industry"],
)
self.assertEqual(
    "declared_industry_denied_by_background",
    judgment_context["context_conflicts"][0]["type"],
)
```

Add negative tests:

- background without `非保健食品` produces no conflict;
- `普通果汁饮品` alone does not deterministically infer a regulatory identity;
- empty background produces no conflict.

- [ ] **Step 2: Run the test and verify RED**

```powershell
py -3 -m unittest test_context_provenance_boundary.py
```

Expected: import or attribute failure because `build_judgment_context_package` does not exist.

- [ ] **Step 3: Implement the private context builder**

Add to `rule_engine.py`:

```python
def _explicit_industry_conflicts(request):
    material = request.get("material", {}) or {}
    context = request.get("context", {}) or {}
    industry = str(context.get("industry") or "").strip()
    background = str(material.get("supplemental_background") or "").strip()
    denial = f"非{industry}" if industry else ""
    if not denial or denial not in background:
        return []
    return [
        {
            "type": "declared_industry_denied_by_background",
            "declared_industry": industry,
            "background_evidence": denial,
            "verification_required": True,
        }
    ]


def build_judgment_context_package(request, public_context_package=None):
    public_context = dict(public_context_package or build_context_package(request))
    material = request.get("material", {}) or {}
    public_context.update(
        {
            "supplemental_background": material.get("supplemental_background", ""),
            "context_provenance": {
                "material_text": "advertising_content",
                "supplemental_background": "operator_supplied_unverified",
                "industry": "recall_and_routing_label",
                "product_category": "operator_structured_unverified",
            },
            "context_conflicts": _explicit_industry_conflicts(request),
        }
    )
    return public_context
```

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
py -3 -m unittest test_context_provenance_boundary.py test_rule_engine_mvp.py test_semantic_recall.py
```

Expected: all tests PASS; keyword and semantic behavior remains unchanged.

- [ ] **Step 5: Commit**

```powershell
git add rule_engine/src/rule_engine.py rule_engine/src/test_context_provenance_boundary.py
git commit -m "feat(rule-engine): add private judgment context provenance"
```

## Task 2: Add prompt policy and deterministic conflict guard

**Files:**
- Modify: `rule_engine/src/llm_judgment.py`
- Modify: `rule_engine/src/test_context_provenance_boundary.py`

- [ ] **Step 1: Add failing prompt-policy tests**

Build messages with a private judgment context and assert the serialized policy says:

- supplemental background is unverified operator information;
- industry is a recall/routing label rather than proof of legal product identity;
- explicit conflicts require product-identity verification;
- general direct-content rules remain independently applicable.

- [ ] **Step 2: Add failing guard tests**

Create candidates:

```python
general_rule = {
    "rule_uid": "RUID-GEN-MED",
    "rule_id": "GEN-MED-001",
    "applies_to": {"industries": ["通用"]},
}
health_rule = {
    "rule_uid": "RUID-HF",
    "rule_id": "HF-002",
    "applies_to": {"industries": ["保健食品"]},
}
```

Create two LLM judgments, both initially `confirmed_violation`. Assert after the guard:

```python
self.assertEqual("confirmed_violation", general_judgment["applicability_status"])
self.assertEqual("needs_fact_verification", health_judgment["applicability_status"])
self.assertIn("核验产品是否属于保健食品", health_judgment["missing_facts"])
```

Also assert:

- no conflict leaves both judgments unchanged;
- `not_applicable` remains unchanged;
- a rule whose industries include `通用` is not downgraded;
- conflict revision advice is replaced with neutral identity-verification advice and does not recommend an industry-specific disclaimer.

- [ ] **Step 3: Run and verify RED**

```powershell
py -3 -m unittest test_context_provenance_boundary.py
```

Expected: failures because policy and `apply_context_provenance_guard` do not exist.

- [ ] **Step 4: Add the judgment policy**

Extend `judgment_policy` with structured text equivalent to:

```json
{
  "context_provenance_policy": "补充背景为运营提供且未经核验；可用于理解和发现冲突，不得单独支持确定违规。",
  "industry_role_policy": "行业字段仅用于召回与路由，不单独证明产品法律属性。",
  "industry_conflict_policy": "存在行业显式冲突时，依赖该身份的专项规则不得仅凭行业字段确认适用。",
  "general_rule_priority": "不依赖产品身份的通用直接内容禁止规则可独立完成判断。"
}
```

Add the ordinary-juice boundary example from the design.

- [ ] **Step 5: Implement the deterministic guard**

Add to `llm_judgment.py`:

```python
def apply_context_provenance_guard(llm_judgment, candidate_rules, context_package):
    # Return a copied judgment payload.
    # Locate explicit declared-industry conflict.
    # Match candidates and judgments by rule_uid, falling back to rule_id.
    # Downgrade confirmed industry-specific rules to needs_fact_verification.
    # Preserve general rules and all non-confirmed statuses.
    # Replace conflict-sensitive revision advice with neutral verification advice.
```

Exact downgrade fields:

```python
judgment["applicability_status"] = "needs_fact_verification"
judgment["judgment"] = "需事实核验"
judgment["missing_facts"] = existing + [f"核验产品是否属于{industry}及相应资质"]
judgment["unsatisfied_elements"] = existing + [f"产品属于{industry}的前提尚未核验"]
judgment["applicability_reason"] = "行业字段仅为召回和路由标签，且补充背景明确否认该产品身份；需先核验产品实际监管属性。"
judgment["reasoning"] = judgment["applicability_reason"]
```

When a conflict exists, set:

```text
revision_suggestion = 删除已确认的直接违法表述，并核验产品实际监管属性；不得以添加行业专属免责声明替代对直接违法文案的删除。
```

- [ ] **Step 6: Run focused tests and verify GREEN**

```powershell
py -3 -m unittest test_context_provenance_boundary.py test_subsumption_contract.py test_llm_judgment_real.py
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```powershell
git add rule_engine/src/llm_judgment.py rule_engine/src/test_context_provenance_boundary.py
git commit -m "fix(rule-engine): enforce industry applicability boundary"
```

## Task 3: Integrate the private context and guard into `/audit`

**Files:**
- Modify: `rule_engine/src/rule_engine.py`
- Modify: `rule_engine/src/test_context_provenance_boundary.py`
- Test: existing audit contract suites.

- [ ] **Step 1: Add a failing audit integration test**

Patch `rule_engine.judge_with_llm` with a fake that:

- captures its received context;
- returns confirmed judgments for `GEN-MED-001` and every health-specific candidate.

Run an audit payload containing:

```text
industry = 保健食品
content = 治疗肝癌、肺癌、结肠癌等80%-90%癌症病类
supplemental_background = 产品为普通果汁饮品，非保健食品
product_category = 果汁饮品
```

Assert:

- fake DeepSeek received supplemental background and provenance;
- public `response["data"]["context_package"]` has exactly the legacy key set;
- `GEN-MED-001` remains confirmed;
- all rules exclusively scoped to `保健食品` are not confirmed;
- `/audit` response keys and types remain compatible.

- [ ] **Step 2: Run and verify RED**

```powershell
py -3 -m unittest test_context_provenance_boundary.py
```

Expected: private context is not yet used by `audit`, or guard is not applied before validation.

- [ ] **Step 3: Integrate into the audit flow**

In `audit()`:

```python
context_package = build_context_package(request)
judgment_context_package = build_judgment_context_package(request, context_package)
...
llm_judgment = _judge_with_config(judgment_context_package, judgment_rules)
llm_judgment = apply_context_provenance_guard(
    llm_judgment,
    judgment_rules,
    judgment_context_package,
)
validated_subsumption = validate_subsumption_result(
    judgment_rules,
    llm_judgment.get("rule_judgments"),
    context_package.get("material_text") or "",
)
```

Continue returning the original `context_package` in `/audit`.

- [ ] **Step 4: Run focused integration and contract tests**

```powershell
py -3 -m unittest test_context_provenance_boundary.py test_audit_contract_subsumption.py test_audit_contract_semantic_scenarios.py test_subsumption_failure_fallback.py test_rule_engine_mvp.py
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add rule_engine/src/rule_engine.py rule_engine/src/test_context_provenance_boundary.py
git commit -m "fix(rule-engine): use provenance-aware judgment context"
```

## Task 4: Full verification and real three-case validation

**Files:**
- No production changes unless a deterministic failure receives a new failing test first.
- Generated reports remain untracked.

- [ ] **Step 1: Run all unit tests**

```powershell
py -3 -m unittest discover -p "test_*.py"
```

Expected: all tests PASS.

- [ ] **Step 2: Run the existing mock baseline**

```powershell
$env:ADSURE_LLM_BACKEND='mock'
$env:ADSURE_LLM_MODE='strict'
$env:ADSURE_SEMANTIC_BACKEND='zhipu'
py -3 .\run_engine_baseline_eval.py --baseline-name mock_strict_zhipu_context_provenance
```

Expected: recall, UID, parent deduplication and public contract metrics do not regress.

- [ ] **Step 3: Run the three real DeepSeek + Zhipu cases twice**

Expected on both runs:

- game: `GAME-FALSE-004` remains fact verification;
- beauty: `GEN-GOOD-CUSTOMS-001` remains confirmed, high risk, legal route;
- ordinary juice:
  - `GEN-MED-001` remains confirmed;
  - rules exclusively scoped to `保健食品` are not confirmed;
  - revision suggestion says to delete treatment language and verify product identity;
  - no advice to cure the issue merely by adding `本品不能代替药物`.

- [ ] **Step 4: Verify public contract and Git quality**

```powershell
git diff --check dev...HEAD
git status --short
```

Compare a representative `/audit` response key set before and after; nested public `context_package` keys must remain unchanged.

- [ ] **Step 5: Record evidence**

Report test counts, both real-run outputs, changed files and remaining model variability. Do not deploy or push until the branch completion workflow is approved.
