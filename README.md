# Ads Penalty RAG

广告行政处罚案例 RAG 的最小可用数据流水线。当前版本默认离线运行，不真实请求网络；真实抓取必须先在 `data/sources/sources.yaml` 手动补充详情页链接，再显式传 `--allow-network`。

## 目录

- `data/sources/sources.yaml`：官方数据源配置。
- `data/raw_html/`：原始 HTML JSON，不覆盖已有 `case_id`。
- `data/raw_text/`：正文抽取结果，不覆盖已有 `case_id`。
- `data/structured/`：真实官方案例结构化 JSON，不覆盖已有 `case_id`。
- `data/structured_samples/`：离线样例结构化 JSON，只用于流水线测试，不进入律师评审案例库。
- `data/structured_archive/`：历史样例或不应进入正式库的数据归档。
- `data/chunks/`：真实官方案例 RAG chunk 和本地词法索引。
- `data/chunks_samples/`：离线样例 RAG chunk，用于 smoke test。
- `data/sources/sample_cases.html`：离线样例页面，仅用于 MVP 流水线测试。
- `data/reports/`：字段校验报告、LLM 请求元数据和失败输出。
- `data/audit_test_cases/`：规则引擎 `/audit` 的真实广告物料测试集，与处罚案例 RAG 分库。
- `prompts/`：清洗、校验和检索测试提示词。
- `src/`：流水线脚本。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 离线跑通完整流程

```bash
make pipeline
```

`make pipeline` 默认使用 `data/sources/sample_cases.html` 和 `sources.yaml` 中的 manual_seed URL，不请求网络。样例数据明确标记为 `offline_sample`，清洗后写入 `data/structured_samples/`，不混入正式 `data/structured/`。

也可以逐步运行：

```bash
python3 src/fetch_cases.py
python3 src/extract_text.py
python3 src/clean_cases.py --mode mock
python3 src/validate_cases.py
python3 src/build_chunks.py
python3 src/build_chunks.py --structured-dir data/structured_samples --chunks-dir data/chunks_samples
python3 src/test_retrieval.py --chunks-path data/chunks_samples/chunks.json --query "普通食品宣传降血糖"
```

`data/chunks/chunks.json` 会为每条案例生成两类 chunk：
- `case_summary`：自然语言场景描述，用于案例场景召回。
- `regulatory_logic`：监管逻辑和违法宣称摘要，用于规则口径召回。

## LLM 清洗模式

```bash
python3 src/clean_cases.py --mode mock
python3 src/clean_cases.py --mode openai
python3 src/clean_cases.py --mode anthropic
```

API key 只从环境变量读取，不写入代码，也不会打印到日志。没有对应 key 时自动退回 `mock` 模式。

环境变量示例见 `.env.example`：

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
LLM_PROVIDER=openai
LLM_MODEL=gpt-5.5
```

真实 LLM 请求会把 `request_id`、`model`、`timestamp`、`provider`、`case_id`、`attempt` 追加写入 `data/reports/llm_runs.jsonl`。如果模型输出不是合法 JSON，原始输出会保存到 `data/reports/failed_outputs/`，每条案例最多重试 2 次。

## 接入真实数据

1. 在 `data/sources/sources.yaml` 为对应来源补充 `detail_urls`，建议首批手动放入 20 个官方详情页。
2. 确认页面属于 `allowed_domains`，且不需要登录、验证码或非公开接口。
3. 未传 `--allow-network` 时，`fetch_cases.py` 只处理带 `sample_file` 的离线样例；传 `--allow-network` 后，只抓取 `detail_urls`，不会全站爬取。
4. 运行：

```bash
python3 src/fetch_cases.py --allow-network
python3 src/extract_text.py
python3 src/clean_cases.py --mode mock
python3 src/validate_cases.py
python3 src/build_chunks.py
python3 src/test_retrieval.py --query "保健食品 宣称 治疗 疾病"
```

后续接 OpenAI/Anthropic 时，继续保留同一 JSON schema 和人工回溯字段。

## `/audit` 真实物料测试集

`data/audit_test_cases/real_mvp_cases_v0.1.json` 从现有待核验候选案例的 `illegal_claims` 中逐字选择广告文案，按美妆、保健食品、游戏、通用广告各 5 条组成首批 20 条回归测试数据。运行：

```bash
make audit-cases
```

该数据集有独立 schema：`input_payload` 是发送给规则引擎 `/audit` 的请求体，`human_reference` 是人工预期，`provenance` 仅用于追溯原候选案例。它不会被 `build_chunks.py` 读取，也不得进入 candidate 或 production RAG。原候选案例均处于 `pending_source_lookup`，因此测试集不能作为已核验处罚事实对外引用。

## 可重复运行规则

- `raw_html`、`raw_text`、`structured` 均按 `case_id` 去重，已存在文件不会被覆盖。
- `offline_sample` 结构化输出写入 `data/structured_samples/`，正式校验默认只看 `data/structured/`。
- `chunks.json` 是派生产物，会按当前输入目录重建，避免旧样例 chunk 混入正式索引。
- `reports/validation_report.md` 和 `chunks/lexical_index.json` 是可再生成产物，会随当前数据刷新。
