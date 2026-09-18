# Cloud Rule + RAG Baseline HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and verify one self-contained, offline, interactive HTML dashboard for the existing 30-case cloud rule-engine and RAG baseline.

**Architecture:** A Python standard-library generator validates the existing JSON, derives comparison metrics, and renders a single UTF-8 HTML document with embedded CSS, JavaScript, SVG/CSS charts, and case data. A separate standard-library verification script treats the HTML as an artifact and checks coverage, offline behavior, required controls, accessibility markers, and secret absence.

**Tech Stack:** Python 3 standard library, HTML5, CSS, vanilla JavaScript, inline SVG/CSS charts.

---

### Task 1: Specify artifact behavior with failing tests

**Files:**
- Create: `rule_engine/test_reports/cloud_joint_baseline_20260918/test_generate_cloud_joint_html.py`
- Test: `rule_engine/test_reports/cloud_joint_baseline_20260918/cloud_rule_rag_baseline_30.json`

- [ ] **Step 1: Write generator contract tests**

Create `test_generate_cloud_joint_html.py` with `unittest` tests that import `generate_cloud_joint_html`, load the real baseline fixture, and assert:

```python
class HtmlReportTests(unittest.TestCase):
    def test_build_model_validates_and_derives_case_outcomes(self):
        model = report.build_model(json.loads(INPUT.read_text(encoding="utf-8")))
        self.assertEqual(30, len(model["cases"]))
        self.assertEqual(3, model["summary"]["rag_nonempty_cases"])
        self.assertEqual(8, model["summary"]["rag_recalled_records"])
        self.assertEqual(25, model["summary"]["expected_uid_hits"])
        self.assertEqual(33, model["summary"]["expected_uid_total"])
        self.assertEqual(2, model["summary"]["routing_matches"])
        self.assertEqual(20, model["summary"]["routing_comparable"])
        game_cases = [case for case in model["cases"] if case["dataset"] == "游戏"]
        self.assertEqual(10, len(game_cases))
        self.assertTrue(all(case["rag_count"] == 0 for case in game_cases))

    def test_render_html_is_offline_and_contains_controls_and_cases(self):
        model = report.build_model(json.loads(INPUT.read_text(encoding="utf-8")))
        html = report.render_html(model)
        self.assertIn('id="dataset-filter"', html)
        self.assertIn('id="rag-filter"', html)
        self.assertIn('id="routing-filter"', html)
        self.assertIn('id="uid-filter"', html)
        self.assertIn('id="case-search"', html)
        self.assertIn("词法降级", html)
        self.assertEqual(30, html.count('class="case-card"'))
        for case in model["cases"]:
            self.assertIn(case["case_id"], html)
        lowered = html.lower()
        for token in ("https://", "http://", "fetch(", "type=\"module\"", "src=\""):
            self.assertNotIn(token, lowered)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
py -3 -m unittest rule_engine.test_reports.cloud_joint_baseline_20260918.test_generate_cloud_joint_html -v
```

Expected: import failure because `generate_cloud_joint_html.py` does not exist.

- [ ] **Step 3: Commit the failing contract test**

```powershell
git add -- rule_engine/test_reports/cloud_joint_baseline_20260918/test_generate_cloud_joint_html.py
git commit -m "test: define cloud baseline html contract"
```

### Task 2: Implement model derivation and offline HTML rendering

**Files:**
- Create: `rule_engine/test_reports/cloud_joint_baseline_20260918/generate_cloud_joint_html.py`
- Generate: `rule_engine/test_reports/cloud_joint_baseline_20260918/CLOUD_RULE_RAG_BASELINE_30.html`
- Test: `rule_engine/test_reports/cloud_joint_baseline_20260918/test_generate_cloud_joint_html.py`

- [ ] **Step 1: Implement validation and derived model**

Implement these public functions:

```python
def percentile(values: list[int], fraction: float) -> float: ...
def build_model(payload: dict) -> dict: ...
def render_html(model: dict) -> str: ...
def main() -> int: ...
```

`build_model` must reject inputs that do not have 30 unique cases or whose RAG `cases` value is not a list. For each case derive `routing_status`, `uid_status`, `rag_count`, `best_similarity`, matched expected/missed UIDs, and searchable text. Derive service success, RAG emptiness, UID recall, routing comparison, dataset outcomes, and latency median/P95.

- [ ] **Step 2: Implement the executive dashboard**

`render_html` must emit:

```html
<header class="hero">...</header>
<section aria-labelledby="kpi-heading" class="kpi-grid">...</section>
<section aria-labelledby="visual-heading" class="visual-grid">...</section>
<section aria-labelledby="priority-heading" class="findings">...</section>
```

Include numeric KPI cards, completion/proportion bars, per-dataset RAG bars, UID/routing bars, latency summaries, and explicit textual interpretations. Show the hybrid-to-lexical degradation warning near the top.

- [ ] **Step 3: Implement the interactive explorer**

Embed controls with stable IDs and accessible labels. Render each case as a native `<details class="case-card">` element with `data-dataset`, `data-rag`, `data-routing`, `data-uid`, and normalized `data-search` attributes. Inline JavaScript must apply AND filtering, update the visible result count, support reset, and provide expand/collapse-all controls. Do not use network APIs.

- [ ] **Step 4: Implement detailed case contents**

Each case must include expected versus actual routing and UIDs, matched rules, service status and latency, and every RAG record with its ID, title, similarity, source, source URL as text/link when present, summary, penalty result, legal basis, mapped rule IDs, and possible liability IDs. Render explicit empty states.

- [ ] **Step 5: Add responsive and print styling**

Use a readable system-font stack, WCAG-conscious contrast, visible focus states, responsive grids, sticky filter controls on wider screens, and `@media print` rules that hide controls and avoid clipping expanded content.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
py -3 -m unittest rule_engine.test_reports.cloud_joint_baseline_20260918.test_generate_cloud_joint_html -v
```

Expected: all tests pass.

- [ ] **Step 7: Generate the artifact**

Run:

```powershell
py -3 rule_engine/test_reports/cloud_joint_baseline_20260918/generate_cloud_joint_html.py
```

Expected: `CLOUD_RULE_RAG_BASELINE_30.html` is created and the command prints its absolute path and byte size.

### Task 3: Verify the artifact and visually inspect it

**Files:**
- Create: `rule_engine/test_reports/cloud_joint_baseline_20260918/verify_cloud_joint_html.py`
- Verify: `rule_engine/test_reports/cloud_joint_baseline_20260918/CLOUD_RULE_RAG_BASELINE_30.html`

- [ ] **Step 1: Write artifact verification**

Create a standard-library verification script that reads the JSON and HTML and asserts:

```python
assert len(cases) == len(set(case_ids)) == 30
assert all(case_id in html for case_id in case_ids)
assert html.count('class="case-card"') == 30
assert sum(len(rag_cases(case)) for case in cases) == 8
assert all(str(item.get("case_id") or "") in html for item in recalled)
assert "词法降级" in html
assert not any(token in html for token in secret_markers)
assert not any(token in html.lower() for token in remote_dependency_markers)
assert all(control_id in html for control_id in required_controls)
```

Print a compact JSON verification summary on success.

- [ ] **Step 2: Run all automated checks**

Run:

```powershell
py -3 -m unittest rule_engine.test_reports.cloud_joint_baseline_20260918.test_generate_cloud_joint_html -v
py -3 -B rule_engine/test_reports/cloud_joint_baseline_20260918/verify_cloud_joint_html.py
```

Expected: tests pass; verification reports 30 cases, 8 recalled records, zero remote dependencies, and zero secrets.

- [ ] **Step 3: Open and visually inspect locally**

Open the generated HTML in the Codex browser/file preview. Check desktop layout, warning prominence, chart labels, search, each filter, reset, expand/collapse, long Chinese text wrapping, empty states, recalled-case details, and narrow viewport behavior.

- [ ] **Step 4: Fix only observed defects and rerun verification**

For each defect, add or strengthen a failing assertion first, then make the smallest renderer/style/script change. Rerun both commands from Step 2 after every correction.

- [ ] **Step 5: Commit the completed report implementation**

```powershell
git add -- rule_engine/test_reports/cloud_joint_baseline_20260918/generate_cloud_joint_html.py rule_engine/test_reports/cloud_joint_baseline_20260918/test_generate_cloud_joint_html.py rule_engine/test_reports/cloud_joint_baseline_20260918/verify_cloud_joint_html.py rule_engine/test_reports/cloud_joint_baseline_20260918/CLOUD_RULE_RAG_BASELINE_30.html
git commit -m "feat: add offline cloud baseline dashboard"
```

Do not add the pre-existing JSON, Markdown, probe output, environment snapshot, or other untracked files unless the user separately asks for them to be committed.
