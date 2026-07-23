# Rule Engine Plain-Text Hit Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace rule-list text in `预审_命中要点` and `审核_高风险词命中` with card-safe plain-language summaries while preserving structured rule IDs and the `/audit` contract.

**Architecture:** Keep recall, candidate governance, DeepSeek subsumption, risk synthesis, routing, and full legal opinion unchanged. Add two deterministic presentation helpers after subsumption: one composes a human-readable risk summary from final rule evidence/reasons, and one extracts plain original evidence for the high-risk-term field. Both helpers operate only on validated final rules and never call an LLM.

**Tech Stack:** Python 3, `unittest`, existing Adsure rule engine modules and JSON rule assets.

---

## File Structure

- Modify `rule_engine/src/rule_engine.py`: add card-safe summary helpers and use them for two existing `/audit` string fields.
- Modify `rule_engine/src/test_rule_engine_mvp.py`: add focused regression tests for safe display fields and preserve rule traceability assertions.
- Modify `rule_engine/src/test_rule_subsumption_cases.py` only if its existing three-case fixtures provide a cleaner integration assertion than duplicating setup in `test_rule_engine_mvp.py`.

No schema, JSON rule, RAG, vector index, Feishu, or environment configuration files change.

### Task 1: Add failing display-field regression tests

**Files:**
- Modify: `rule_engine/src/test_rule_engine_mvp.py`

- [ ] **Step 1: Import the new helper names expected by the tests**

Extend the existing import from `rule_engine` with:

```python
from rule_engine import (
    _card_hit_summary,
    _high_risk_evidence_summary,
    # existing imports remain unchanged
)
```

- [ ] **Step 2: Add a unit test for a confirmed violation summary**

```python
def test_card_hit_summary_uses_plain_evidence_and_reason_without_rule_id(self):
    rules = [
        {
            "rule_id": "GEN-GOOD-CUSTOMS-001",
            "title": "广告不得妨碍公共秩序或违背社会良好风尚",
            "applicability_status": "confirmed_violation",
            "material_evidence": "和狗一样跑过来",
            "applicability_reason": "将消费者作动物化贬损，违背社会良好风尚。",
        }
    ]

    summary = _card_hit_summary(rules)

    self.assertIn("和狗一样跑过来", summary)
    self.assertIn("违背社会良好风尚", summary)
    self.assertNotIn("GEN-GOOD-CUSTOMS-001", summary)
    self.assertNotIn("[", summary)
    self.assertNotIn("]", summary)
    self.assertNotIn("regex:", summary)
```

- [ ] **Step 3: Add a unit test for fact verification and evidence extraction**

```python
def test_card_summaries_keep_missing_facts_and_plain_original_evidence(self):
    rules = [
        {
            "rule_id": "GAME-FALSE-004",
            "title": "禁止虚假广告（虚构使用效果）",
            "applicability_status": "needs_fact_verification",
            "material_evidence": "开局十连抽，爆率拉满，神装随便出",
            "applicability_reason": "该表述可能使玩家形成高概率获得装备的预期。",
            "missing_facts": ["游戏实际奖池、概率、保底和适用条件资料"],
        }
    ]

    hit_summary = _card_hit_summary(rules)
    evidence_summary = _high_risk_evidence_summary(rules)

    self.assertIn("高概率", hit_summary)
    self.assertIn("游戏实际奖池、概率、保底和适用条件资料", hit_summary)
    self.assertEqual("开局十连抽，爆率拉满，神装随便出", evidence_summary)
    for value in (hit_summary, evidence_summary):
        self.assertNotIn("GAME-FALSE-004", value)
        self.assertNotIn("[", value)
        self.assertNotIn("]", value)
        self.assertNotIn("regex:", value)
```

- [ ] **Step 4: Add an integration regression assertion to the existing standard response test**

After obtaining `data` in `test_rule_engine_returns_standard_mvp_response`, add:

```python
for field in ("预审_命中要点", "审核_高风险词命中"):
    self.assertIsInstance(data[field], str)
    self.assertNotIn("[", data[field])
    self.assertNotIn("]", data[field])
    self.assertNotIn("regex:", data[field])

self.assertTrue(any(rule.get("rule_id") for rule in data["matched_rules"]))
self.assertIn("[", data["审核_审核意见"])
```

- [ ] **Step 5: Run the focused tests and verify RED**

Run:

```powershell
Set-Location "D:\G-Vibe coding\广告合规审查智能体\Adsure\rule_engine\src"
py -3 -m unittest test_rule_engine_mvp.RuleEngineMvpTests.test_card_hit_summary_uses_plain_evidence_and_reason_without_rule_id test_rule_engine_mvp.RuleEngineMvpTests.test_card_summaries_keep_missing_facts_and_plain_original_evidence test_rule_engine_mvp.RuleEngineMvpTests.test_rule_engine_returns_standard_mvp_response
```

Expected: FAIL because `_card_hit_summary` and `_high_risk_evidence_summary` do not exist, or because the existing fields still contain `[RULE-ID]`.

- [ ] **Step 6: Commit the RED tests**

```powershell
git add rule_engine/src/test_rule_engine_mvp.py
git commit -m "test(rule-engine): require plain text card summaries"
```

### Task 2: Implement deterministic plain-text summaries

**Files:**
- Modify: `rule_engine/src/rule_engine.py`
- Test: `rule_engine/src/test_rule_engine_mvp.py`

- [ ] **Step 1: Add a plain-text normalization helper near `_precheck_hit_summary`**

```python
def _plain_card_text(value):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"regex:.*$", "", text).strip()
    text = text.replace("[", "").replace("]", "")
    return text
```

This helper is a final safety boundary. It does not attempt general Markdown rendering and does not change structured fields.

- [ ] **Step 2: Add the human-readable card summary helper**

```python
def _card_rule_sentence(rule):
    evidence = _plain_card_text(rule.get("material_evidence"))
    reason = _plain_card_text(rule.get("applicability_reason"))
    title = _plain_card_text(rule.get("title"))
    status = rule.get("applicability_status")
    missing = [
        _plain_card_text(item)
        for item in (rule.get("missing_facts") or [])
        if _plain_card_text(item)
    ]

    if reason:
        sentence = reason
    elif evidence and title:
        sentence = f"“{evidence}”涉及{title}。"
    elif title:
        sentence = f"该物料涉及{title}。"
    else:
        sentence = "该物料存在广告合规风险。"

    if evidence and evidence not in sentence:
        sentence = f"“{evidence}”：{sentence}"
    if status == "needs_fact_verification" and missing:
        sentence = sentence.rstrip("。；") + "，需核验" + "、".join(missing) + "。"
    return _plain_card_text(sentence)


def _card_hit_summary(matched_rules):
    if not matched_rules:
        return "无明显命中"
    confirmed = [
        rule for rule in matched_rules
        if rule.get("applicability_status") == "confirmed_violation"
    ]
    fact_rules = [
        rule for rule in matched_rules
        if rule.get("applicability_status") == "needs_fact_verification"
    ]
    selected = confirmed[:1]
    if fact_rules:
        selected.append(fact_rules[0])
    if not selected:
        selected = matched_rules[:1]
    return "；".join(_card_rule_sentence(rule).rstrip("；") for rule in selected if rule)
```

The function deliberately selects at most one confirmed rule and one fact-verification rule so the card remains concise.

- [ ] **Step 3: Add the high-risk evidence helper**

```python
def _high_risk_evidence_summary(matched_rules):
    evidence = []
    for rule in matched_rules:
        text = _plain_card_text(rule.get("material_evidence"))
        if text and text not in evidence:
            evidence.append(text)
    return "、".join(evidence) if evidence else "无"
```

- [ ] **Step 4: Wire the helpers into the existing response without changing keys**

Replace:

```python
"预审_命中要点": _precheck_hit_summary(matched_rules),
```

with:

```python
"预审_命中要点": _card_hit_summary(matched_rules),
```

Replace:

```python
"审核_高风险词命中": _precheck_hit_summary(matched_rules) if matched_rules else "无",
```

with:

```python
"审核_高风险词命中": _high_risk_evidence_summary(matched_rules),
```

Do not modify `_precheck_hit_summary` because it may remain useful for non-card diagnostics and compatibility tests.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run the same three-test command from Task 1.

Expected: `Ran 3 tests ... OK`.

- [ ] **Step 6: Run adjacent contract tests**

```powershell
py -3 -m unittest test_audit_contract_semantic_scenarios.py test_audit_contract_subsumption.py test_confirmed_outcome.py test_rule_engine_mvp.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit the implementation**

```powershell
git add rule_engine/src/rule_engine.py rule_engine/src/test_rule_engine_mvp.py
git commit -m "fix(rule-engine): return plain text card summaries"
```

### Task 3: Add representative-case regression coverage

**Files:**
- Modify: `rule_engine/src/test_rule_subsumption_cases.py` or `rule_engine/src/test_rule_engine_mvp.py`

- [ ] **Step 1: Add three integration assertions using existing mock/subsumption fixtures**

For each existing game, beauty, and health response, assert:

```python
for field in ("预审_命中要点", "审核_高风险词命中"):
    value = response["data"][field]
    self.assertIsInstance(value, str)
    self.assertNotIn("[", value)
    self.assertNotIn("]", value)
    self.assertNotIn("regex:", value)
```

Add case-specific assertions:

```python
self.assertIn("爆率", game_response["data"]["预审_命中要点"])
self.assertIn("和狗一样跑过来", beauty_response["data"]["预审_命中要点"])
self.assertIn("治疗", health_response["data"]["预审_命中要点"])
```

Also verify traceability remains:

```python
self.assertIn("GAME-FALSE-004", {r["rule_id"] for r in game_response["data"]["matched_rules"]})
self.assertIn("GEN-GOOD-CUSTOMS-001", {r["rule_id"] for r in beauty_response["data"]["matched_rules"]})
self.assertIn("GEN-MED-001", {r["rule_id"] for r in health_response["data"]["matched_rules"]})
```

- [ ] **Step 2: Run the new case tests**

Run the exact test class or methods containing these three fixtures.

Expected: all new assertions pass without real DeepSeek or Zhipu calls.

- [ ] **Step 3: Commit the representative-case tests**

```powershell
git add rule_engine/src/test_rule_subsumption_cases.py rule_engine/src/test_rule_engine_mvp.py
git commit -m "test(rule-engine): cover safe summaries in legal cases"
```

### Task 4: Full regression and contract verification

**Files:**
- No production changes expected.

- [ ] **Step 1: Run the complete unit-test suite**

```powershell
Set-Location "D:\G-Vibe coding\广告合规审查智能体\Adsure\rule_engine\src"
py -3 -m unittest discover -p "test_*.py"
```

Expected: all tests pass with zero failures and zero errors.

- [ ] **Step 2: Run a local three-case presentation check without external model calls**

Use existing mock/subsumption fixtures or a focused test runner to print only:

```text
case
预审_命中要点
审核_高风险词命中
matched rule IDs
```

Expected:

- card fields contain no square brackets or `regex:`;
- game summary retains probability verification meaning;
- beauty summary retains consumer-dehumanization meaning;
- health summary retains disease-treatment meaning;
- structured rule IDs remain present.

- [ ] **Step 3: Verify the public schema is unchanged**

```powershell
git diff -- rule_engine/schema rule_engine/src/audit_api.py rule_engine/src/field_mapper.py
```

Expected: no diff.

- [ ] **Step 4: Review the final diff**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intended source, test, and plan files are changed or committed. Existing unrelated untracked reports remain untouched.

- [ ] **Step 5: Commit any final test-only adjustment**

If Task 4 required a test-only correction, commit only that file:

```powershell
git add rule_engine/src/test_rule_engine_mvp.py rule_engine/src/test_rule_subsumption_cases.py
git commit -m "test(rule-engine): finalize card summary regression"
```

Do not commit historical untracked reports.
