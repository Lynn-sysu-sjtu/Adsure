# Cloud Rule + RAG Baseline HTML Report Design

## Goal

Create one self-contained HTML file for the completed 30-case cloud baseline. It must be easy to present, easy to share, and fully usable offline.

## Audience and reading order

The default view serves managers and cross-functional teammates first. It presents conclusions and risk signals before implementation details. Developers can then filter, search, and expand individual cases without leaving the page.

## Deliverables

- `CLOUD_RULE_RAG_BASELINE_30.html`: the shareable offline report.
- A deterministic generator that reads the existing baseline JSON and emits the HTML.
- Automated verification for case coverage, embedded data, offline dependencies, and absence of secrets.

The existing JSON and Markdown reports remain unchanged.

## Information architecture

### Executive header

Show the timestamp, frozen input hash, rule release, RAG index version, and a prominent warning that requested hybrid RAG effectively ran in lexical mode because the semantic model was unavailable.

### KPI cards

Show rule and RAG success, resolved expected UID hits, complete UID-hit cases, routing agreement, non-empty RAG retrieval, and rule/RAG latency. Green means verified success, amber means attention, and red means a material gap.

### Visual summaries

Use inline SVG or CSS, without an external chart library:

- Rule and RAG service completion bars.
- RAG non-empty versus empty retrieval.
- Retrieval outcome by dataset, clearly showing all ten game cases were empty.
- Expected UID recall and routing agreement.
- Rule and RAG latency summaries.

Every chart includes numeric labels and a short interpretation, so meaning never depends on color alone.

### Priority findings

Highlight that 27 of 30 cases had no RAG result, all game cases were empty, semantic retrieval was unavailable, routing matched 2 of 20 expectations, and returned similarities were low.

### Interactive case explorer

Provide client-side filters for dataset, RAG outcome, routing outcome, and expected UID outcome. Add text search across case IDs, copy, rules, and recalled cases; reset controls; and a visible result count. Filters use AND semantics and require no server.

### Per-case cards

Collapsed cards show case ID, dataset, test copy, risk, routing, expected UID outcome, RAG count, best similarity, and status badges. Expanded cards show frozen expectations, expected IDs and UIDs, every matched rule, service status and latency, and every recalled case with title, ID, similarity, source, URL, summary, penalty, legal basis, and mapped IDs. Empty retrieval is explicit.

## Technical design

The generator reads `cloud_rule_rag_baseline_30.json`, derives metrics, escapes source strings, and emits one UTF-8 HTML file. CSS, SVG, JavaScript, and data are embedded. There are no CDN references, remote fonts, fetch calls, modules, or image dependencies.

Use semantic HTML, keyboard-accessible controls, native expandable sections, responsive CSS, and a print layout that hides controls and preserves readable content.

## Data flow

1. Read and validate the baseline JSON.
2. Derive dataset, routing, UID recall, RAG outcome, and latency metrics.
3. Serialize only fields required by the dashboard and explorer.
4. Embed data and render the initial dashboard.
5. Apply all filtering locally in the browser.

## Error handling

Stop generation if JSON is missing, malformed, lacks exactly 30 unique cases, or has an invalid RAG cases type. Missing optional fields render as an em dash.

## Verification

Automated checks confirm successful generation, all 30 case IDs, all eight recalled records and titles, the lexical-degradation warning, no secret markers, no remote dependencies or network calls, and presence of required filters and accessibility labels. The report also receives a local visual smoke check.

## Scope boundaries

This does not change the rule engine, RAG service, deployment, frozen input, baseline JSON, or Markdown report. It does not fix retrieval or routing quality; it only makes the existing evidence easier to understand and share.
