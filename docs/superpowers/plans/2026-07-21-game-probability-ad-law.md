# Game Probability Advertising Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the existing Advertising Law rule `GAME-FALSE-004` so game loot-rate advertising is recalled through scenario vectors and is judged through separate disclosure/misleading and truthfulness-verification nodes without changing the `/audit` contract.

**Architecture:** Keep the existing parent rule, dual IDs, parent-rule deduplication, and three-way recall pipeline unchanged. Add five short semantic scenarios and explicit fact-verification guidance inside `GAME-FALSE-004`, add one regression case to the existing baseline corpus, rebuild the Zhipu vector index, and verify both mock and real DeepSeek behavior.

**Tech Stack:** Python 3, `unittest`, JSON rule assets, Zhipu `embedding-3`, existing Adsure rule-vector index, existing DeepSeek strict subsumption pipeline.

---

## File Map

- Modify: `rule_engine/jsonbase/游戏/20260705_中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载_规则拆解_v1.json`
  - Owns the existing `GAME-FALSE-004` parent rule and its new probability-advertising scenarios.
- Create: `rule_engine/src/test_game_probability_rule_assets.py`
  - Locks the five scenario IDs, legal wording boundary, required materials, legacy IDs, and baseline case.
- Modify: `rule_engine/test_cases/rule_engine_cases_v0.1.json`
  - Adds the real game loot-rate advertising case to the permanent baseline.
- Rebuild: `rule_engine/vectorbase/rule_vector_index.json`
  - Stores Zhipu embeddings for the new scenario vectors.
- Generated only, do not commit unless repository policy already tracks the selected report: `rule_engine/test_reports/*.json`
  - Captures mock and real baseline evidence.

## Task 1: Add failing rule-asset tests

**Files:**
- Create: `rule_engine/src/test_game_probability_rule_assets.py`
- Read: `rule_engine/jsonbase/游戏/20260705_中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载_规则拆解_v1.json`

- [ ] **Step 1: Write a focused test that locates `GAME-FALSE-004` without hard-coding mojibake paths**

```python
import json
import unittest
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]
GAME_AD_LAW_PATH = next(
    path
    for path in (PROJECT_BASE / "jsonbase" / "游戏").glob("*中华人民共和国广告法*规则拆解_v1.json")
)
CASE_PATH = PROJECT_BASE / "test_cases" / "rule_engine_cases_v0.1.json"


class GameProbabilityRuleAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = json.loads(GAME_AD_LAW_PATH.read_text(encoding="utf-8-sig"))
        cls.rule = next(rule for rule in document["rules"] if rule["rule_id"] == "GAME-FALSE-004")

    def test_game_false_rule_contains_probability_scenarios(self):
        scenarios = {
            item["scenario_id"]: item
            for item in self.rule["recall"]["semantic_scenarios"]
        }
        expected = {
            "loot_rate_exaggeration",
            "guaranteed_reward_claim",
            "probability_conditions_omitted",
            "loot_pool_mismatch",
            "guarantee_conditions_hidden",
        }
        self.assertEqual(expected, set(scenarios))
        self.assertTrue(all(item.get("enabled") is True for item in scenarios.values()))
        self.assertTrue(all(len(item["vector_text"]) <= 50 for item in scenarios.values()))

    def test_game_false_rule_preserves_identity_and_legal_boundary(self):
        self.assertEqual("RUID-fcb662545294a3a6", self.rule["rule_uid"])
        self.assertEqual("fallback", self.rule["recall"]["semantic_role"])
        decision = self.rule["detection"]["decision"]
        self.assertIn("needs_fact_verification", decision)
        self.assertIn("confirmed_violation", decision)
        self.assertNotIn("广告法规定概率公示义务", decision)

    def test_game_false_rule_requests_probability_mechanism_materials(self):
        materials = set(self.rule["fact_check"]["required_materials"])
        self.assertTrue({
            "游戏内或官网概率公示页",
            "实际奖池配置",
            "各等级道具掉落概率",
            "保底机制",
            "活动期限和适用对象",
        }.issubset(materials))

    def test_game_probability_case_is_in_permanent_baseline(self):
        cases = json.loads(CASE_PATH.read_text(encoding="utf-8"))
        case = next(item for item in cases if item["case_id"] == "CASE-GAME-PROB-001")
        self.assertEqual(["GAME-FALSE-004"], case["expected"]["must_recall_rule_ids"])
        self.assertEqual(
            ["GAME-FALSE-004"],
            case["expected"]["expected_fact_verification_rule_ids"],
        )
        self.assertEqual([], case["expected"]["expected_confirmed_rule_ids"])
```

- [ ] **Step 2: Run the focused test and verify RED**

Run from `rule_engine/src`:

```powershell
py -3 -m unittest test_game_probability_rule_assets.py
```

Expected: FAIL because `semantic_scenarios` and `CASE-GAME-PROB-001` do not exist.

- [ ] **Step 3: Commit the failing test**

```powershell
git add rule_engine/src/test_game_probability_rule_assets.py
git commit -m "test(rule-engine): specify game probability ad assets"
```

## Task 2: Enhance `GAME-FALSE-004` and add the baseline case

**Files:**
- Modify: `rule_engine/jsonbase/游戏/20260705_中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载_规则拆解_v1.json`
- Modify: `rule_engine/test_cases/rule_engine_cases_v0.1.json`
- Test: `rule_engine/src/test_game_probability_rule_assets.py`

- [ ] **Step 1: Add five enabled semantic scenarios to `GAME-FALSE-004.recall`**

```json
"semantic_scenarios": [
  {
    "scenario_id": "loot_rate_exaggeration",
    "vector_text": "宣称抽卡爆率拉满稀有装备和角色随便获得",
    "enabled": true
  },
  {
    "scenario_id": "guaranteed_reward_claim",
    "vector_text": "将随机抽取奖励宣传为十连必出一抽必中",
    "enabled": true
  },
  {
    "scenario_id": "probability_conditions_omitted",
    "vector_text": "宣传高爆率却未说明奖池保底期限和适用条件",
    "enabled": true
  },
  {
    "scenario_id": "loot_pool_mismatch",
    "vector_text": "广告展示神装稀有角色但实际奖池没有或极难获得",
    "enabled": true
  },
  {
    "scenario_id": "guarantee_conditions_hidden",
    "vector_text": "十连必出承诺隐藏累计次数新用户或付费门槛",
    "enabled": true
  }
]
```

- [ ] **Step 2: Replace detection guidance with the two legal judgment nodes**

Set `semantic_criteria` to:

```text
广告对抽卡、装备掉落或随机奖励的概率和获取难度作出宣传时，核对是否遗漏足以影响消费决策的奖池、保底、期限或适用条件，以及宣传的概率和获取结果是否与实际机制相符。
```

Set `decision` to:

```text
缺少实际奖池、概率、保底和适用条件资料时标记 needs_fact_verification；已有连续原文证据证明概率承诺、必出结果或奖池与实际明显不符，且足以影响用户下载、充值或抽取决策时标记 confirmed_violation。
```

- [ ] **Step 3: Expand fact-verification materials**

Set `fact_check.required_materials` to include:

```json
[
  "游戏内或官网概率公示页",
  "实际奖池配置",
  "各等级道具掉落概率",
  "保底机制",
  "活动期限和适用对象",
  "概率宣传与实际机制的对照说明"
]
```

Keep `rule_id`, `rule_uid`, `legal_basis`, `risk_level`, `semantic_role`, and routing fields unchanged.

- [ ] **Step 4: Append the permanent baseline case**

```json
{
  "case_id": "CASE-GAME-PROB-001",
  "name": "游戏十连抽爆率和神装获取宣传",
  "input_payload": {
    "record_id": "case-game-prob-001",
    "mode": "标准",
    "fields": {
      "①运营·行业领域": "游戏",
      "①运营·物料内容": "开局十连抽，爆率拉满，神装随便出",
      "①运营·补充背景资料": "买量信息流广告，尚未提供实际概率、奖池和保底机制"
    }
  },
  "expected": {
    "must_recall_rule_ids": ["GAME-FALSE-004"],
    "expected_confirmed_rule_ids": [],
    "expected_fact_verification_rule_ids": ["GAME-FALSE-004"],
    "expected_dimensions": ["虚假宣传"],
    "expected_risk_level": "中",
    "expected_routing": "法务"
  }
}
```

- [ ] **Step 5: Run the focused test and verify GREEN**

```powershell
py -3 -m unittest test_game_probability_rule_assets.py
```

Expected: all tests PASS.

- [ ] **Step 6: Run asset and semantic regression tests**

```powershell
py -3 -m unittest test_game_probability_rule_assets.py test_rule_asset_validator.py test_semantic_scenario_assets.py test_rule_vector_index.py test_semantic_recall.py test_audit_contract_semantic_scenarios.py
```

Expected: all tests PASS; `/audit` contract tests remain unchanged.

- [ ] **Step 7: Commit the rule and baseline asset changes**

```powershell
git add rule_engine/jsonbase/游戏/20260705_中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载_规则拆解_v1.json rule_engine/test_cases/rule_engine_cases_v0.1.json
git commit -m "feat(rule-engine): add game probability ad scenarios"
```

## Task 3: Rebuild and validate the Zhipu vector index

**Files:**
- Rebuild: `rule_engine/vectorbase/rule_vector_index.json`
- Test: `rule_engine/src/test_rule_vector_index.py`
- Test: `rule_engine/src/test_rule_uid_vector_identity.py`

- [ ] **Step 1: Confirm the real Zhipu environment without printing keys**

```powershell
Get-ChildItem Env:ADSURE_SEMANTIC_BACKEND,Env:ZHIPU_EMBEDDING_MODEL,Env:ADSURE_SEMANTIC_THRESHOLD -ErrorAction SilentlyContinue
if ([string]::IsNullOrWhiteSpace($env:ZHIPU_API_KEY) -and [string]::IsNullOrWhiteSpace($env:ZHIPUAI_API_KEY)) { throw "Missing Zhipu API key" }
```

Expected: backend is `zhipu`, model is `embedding-3` or defaults to it, and no key value is printed.

- [ ] **Step 2: Rebuild the vector index**

Run from `rule_engine/src`:

```powershell
$env:ADSURE_SEMANTIC_BACKEND='zhipu'
$env:ZHIPU_EMBEDDING_MODEL='embedding-3'
py -3 .\build_rule_vector_index.py
```

Expected: command completes successfully and updates the cached index with five `GAME-FALSE-004` scenario records.

- [ ] **Step 3: Verify the rebuilt index contains exactly the new scenario identities**

```powershell
py -3 -c "import json,pathlib; p=pathlib.Path('../vectorbase/rule_vector_index.json'); d=json.loads(p.read_text(encoding='utf-8')); rows=[x for x in d.get('items',d.get('vectors',[])) if x.get('rule_id')=='GAME-FALSE-004']; print([(x.get('scenario_id'),x.get('vector_text')) for x in rows])"
```

Expected: output contains all five scenario IDs and does not create a second parent `rule_uid`.

- [ ] **Step 4: Run vector identity and semantic tests**

```powershell
py -3 -m unittest test_rule_vector_index.py test_rule_uid_vector_identity.py test_semantic_recall.py test_game_probability_rule_assets.py
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the rebuilt index**

```powershell
git add rule_engine/vectorbase/rule_vector_index.json
git commit -m "build(rule-engine): rebuild game probability vectors"
```

## Task 4: Validate mock behavior, real DeepSeek subsumption, and contract stability

**Files:**
- Read: `rule_engine/test_cases/rule_engine_cases_v0.1.json`
- Generated: `rule_engine/test_reports/*.json`
- Modify only if a reproducible regression is found: tests first, then the smallest in-scope asset correction.

- [ ] **Step 1: Run the full local unit-test suite**

Run from `rule_engine/src`:

```powershell
py -3 -m unittest discover -p "test_*.py"
```

Expected: all tests PASS.

- [ ] **Step 2: Run the mock strict + Zhipu baseline**

```powershell
$env:ADSURE_LLM_BACKEND='mock'
$env:ADSURE_LLM_MODE='strict'
$env:ADSURE_SEMANTIC_BACKEND='zhipu'
$env:ADSURE_SEMANTIC_THRESHOLD='0.50'
$env:ADSURE_FALLBACK_SEMANTIC_THRESHOLD='0.55'
py -3 .\run_engine_baseline_eval.py --baseline-name mock_strict_zhipu_game_probability
```

Expected: `CASE-GAME-PROB-001` recalls `GAME-FALSE-004`; existing recall, dimension, routing, UID, and contract metrics do not regress.

- [ ] **Step 3: Run the real DeepSeek strict + Zhipu baseline**

```powershell
$env:ADSURE_LLM_BACKEND='deepseek'
$env:ADSURE_LLM_MODE='strict'
$env:ADSURE_SEMANTIC_BACKEND='zhipu'
$env:ADSURE_SEMANTIC_THRESHOLD='0.50'
$env:ADSURE_FALLBACK_SEMANTIC_THRESHOLD='0.55'
py -3 .\run_engine_baseline_eval.py --baseline-name deepseek_strict_zhipu_game_probability
```

Expected for `CASE-GAME-PROB-001`:

```text
fallback_reason_code: None
GAME-FALSE-004: needs_fact_verification
GAME-FALSE-004 parent count: 1
```

The requested materials should cover probability disclosure, pool configuration, drop rates, guarantee mechanism, duration, and audience conditions. The model must not claim a standalone Advertising Law probability-disclosure offence.

- [ ] **Step 4: Run a controlled confirmed-violation probe with supplied contradictory facts**

Call the local engine with advertising content `十连必出SSR` and background facts stating `后台配置显示只有累计抽取200次才触发保底`。

Expected:

```text
fallback_reason_code: None
GAME-FALSE-004: confirmed_violation
material_evidence: a continuous original substring from the submitted content or background
```

- [ ] **Step 5: Compare the permanent baseline report with the prior baseline**

Confirm:

- no unexpected new confirmed violations in unrelated cases;
- no duplicate `GAME-FALSE-004` parent rule;
- `/audit` keys and value types are unchanged;
- the game case is fact verification rather than automatic false-ad confirmation;
- all cited rules are candidate rule IDs/UIDs already supplied to DeepSeek.

- [ ] **Step 6: Commit any deterministic test-only calibration made through a new RED/GREEN cycle**

Do not tune global thresholds or `GEN-FALSE-001` for this case. If the real baseline fails probabilistically, rerun once before changing an asset. Any deterministic correction must first be represented by a failing test.

## Task 5: Final verification and handoff

**Files:**
- Verify all changed files and commits.

- [ ] **Step 1: Run final focused verification**

```powershell
py -3 -m unittest test_game_probability_rule_assets.py test_rule_asset_validator.py test_semantic_scenario_assets.py test_rule_vector_index.py test_rule_uid_vector_identity.py test_semantic_recall.py test_audit_contract_semantic_scenarios.py
```

Expected: all tests PASS.

- [ ] **Step 2: Check JSON validity and Git diff quality**

```powershell
py -3 -m json.tool "..\jsonbase\游戏\20260705_中华人民共和国广告法（2021修正）_2021.04.29生效_20260615下载_规则拆解_v1.json" > $null
py -3 -m json.tool "..\test_cases\rule_engine_cases_v0.1.json" > $null
git diff --check dev...HEAD
git status --short
```

Expected: valid JSON, no whitespace errors, and only the planned files or deliberately generated reports are changed.

- [ ] **Step 3: Summarize evidence**

Report:

- exact commits;
- unit-test counts;
- vector index scenario count and matched scenario for the game case;
- mock and real baseline outcome for `CASE-GAME-PROB-001`;
- confirmed-violation probe outcome;
- confirmation that `/audit`, dual IDs, parent-rule deduplication, and Feishu integration remain unchanged.

