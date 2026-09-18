# 裁决回流数据（append-only JSONL）

法务在飞书里对每条风险的裁决结果，经 `POST /api/jobs/{id}/adjudication` 沉淀。
三个文件按回流去向分流：

- `lexicon_feedback.jsonl` — 误报/漏报/不适用 → 词库校准建议（`build_lexicon_suggestions` 聚合）
- `case_feedback.jsonl`    — 确认违规 → 类案库候选（review_status=pending，人工核验后才可引用）
- `ip_feedback.jsonl`      — IP 确认/否决 → 底库参考图收集与 VLM 负样本依据

**append-only**：只追加不修改；每条带 job_id + finding 定位 + 裁决人，可回溯原始证据。
**不自动生效**：词库/阈值修改必须经人工 review 建议后应用，防止单条错误裁决污染词库。
