# Ads Penalty RAG（广告合规 AI 案例库）

面向广告合规审核的行政处罚案例库与规则 RAG 基础工程。仓库将官方处罚材料、待核验候选材料和规则引擎测试物料严格分开，提供可重复执行的导入、清洗、校验、切片和本地检索链路。

当前版本已完成离线数据流水线、Excel/DOCX 候选案例导入、行业候选切片、`/audit` 回归测试数据、飞书/法务工作台联调契约和北大法宝 MCP 的安全配置；尚未提供可部署的 HTTP 服务、Embedding 或生产向量数据库。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 不访问网络，跑通样例抓取、清洗、校验、切片和检索
make pipeline

# 运行全部自动化测试
python3 -m unittest discover -s tests -v
```

默认流程只读取仓库内离线样例，不会发起真实网络请求。真实抓取必须先在 `data/sources/sources.yaml` 中人工填写官方详情页 URL，再显式执行 `python3 src/fetch_cases.py --allow-network`。

## 已交付能力

| 范围 | 实现 | 入口 |
| --- | --- | --- |
| 官方案例流水线 | 获取、正文提取、LLM/Mock 清洗、字段校验、RAG 切片 | `make pipeline` |
| 候选案例导入 | Excel 与行业 DOCX 导入；候选数据不进入生产库 | `make candidate-pipeline`、`make sector-candidate-pipeline` |
| 本地检索 | `case_summary` 与 `regulatory_logic` 两类切片，中文 BM25 词法召回 | `python3 src/test_retrieval.py --query "保健品 会销 降血压"` |
| 审核回归数据 | 20 条真实广告文案测试集及独立校验 | `make audit-cases` |
| 联调设计 | 飞书状态机、规则引擎与案例库的请求、响应、边界与验收口径 | `docs/案例库接入接口确认稿.md` |
| 权威法律检索 | 项目级北大法宝 MCP 配置与可复用安装器；凭证仅由环境变量注入 | `docs/北大法宝MCP接入.md`、`tools/pkulaw_mcp/install.py` |

## 数据边界与入库规则

| 目录 / 数据类型 | 用途 | 是否可作为生产 RAG 处罚事实 |
| --- | --- | --- |
| `data/raw_html/`、`data/raw_text/` | 原始网页与正文，保留人工回溯证据 | 不能直接检索 |
| `data/structured/` | 已核验的官方处罚案例 | 可以，经审核后构建生产切片 |
| `data/structured_samples/` | 纯离线样例 | 不可以 |
| `data/structured_candidates/` | Excel/DOCX 导入的待核验候选案例 | 不可以 |
| `data/audit_test_cases/` | 规则引擎 `/audit` 回归测试物料 | 不可以 |
| `data/chunks/production_chunks.json` | 生产检索索引目标 | 只可由已审核官方案例生成 |

每条正式案例都必须保留 `case_id`、`source_url`、`raw_text_path`、处罚机关、法律依据、处罚结果、`vector_text` 与审核状态。`vector_text` 必须是自然语言场景说明，不能堆砌关键词。司法案例、候选案例和审核测试样本均不能替代行政处罚事实。

## 常用命令

```bash
# 从 Excel / DOCX 重新导入候选案例并做检索回归
make candidate-pipeline
make sector-candidate-pipeline

# 单独校验和构建切片
make validate
make chunks

# 构建并校验 /audit 测试集
make audit-cases

# 只运行本地检索
make test
```

LLM 清洗支持 Mock、OpenAI 和 Anthropic：

```bash
python3 src/clean_cases.py --mode mock
python3 src/clean_cases.py --mode openai
python3 src/clean_cases.py --mode anthropic
```

将 `.env.example` 中的变量设置到本地环境即可。任何 API Key、Token、Cookie、内网地址或带凭证的调用示例都不得提交到仓库；缺少 LLM Key 时会安全回退到 Mock 模式。

## 当前系统边界

- 已实现的是本地文件流水线和 BM25 词法检索；`vector_text` 是检索素材，不代表已部署向量库。
- 当前没有 Flask、FastAPI 或 `POST /cases/retrieve` 路由；接口契约是队友可据以实现的目标设计，不能表述为已上线服务。
- 生产环境只能使用 `production_chunks.json`；候选索引仅可在隔离联调环境中显式启用，且必须返回候选态标记。
- 实际访问官方页面时，必须遵守 `allowed_domains`、robots 和访问频率限制；不得绕过登录、验证码或调用非公开接口。

## 项目结构

```text
src/                         流水线、导入器、校验器、切片与本地检索
tests/                       单元测试与端到端验收测试
data/sources/                官方来源配置与离线样例页面
data/raw_html/ raw_text/     原始材料和正文，按 case_id 保留
data/structured*/            正式、样例、归档和候选结构化案例
data/chunks*/                生产、候选、样例和测试切片索引
data/audit_test_cases/       与案例库隔离的 /audit 回归测试数据
data/reports/                校验、导入和选样报告
data/mappings/               候选案例到规则的映射建议
prompts/                     清洗、校验和检索测试提示词
docs/                        接口契约、联调说明和 MCP 接入说明
scripts/                     本地安全配置辅助脚本
tools/pkulaw_mcp/            可复用 MCP 配置安装与本地审计工具
.codex/config.toml           项目级 MCP 服务定义（不含任何凭证）
```

## 联调与文档入口

- [案例库接入接口确认稿](docs/案例库接入接口确认稿.md)：当前唯一接口口径，区分 `/audit` 与未来的 `/cases/retrieve`。
- [案例库联调说明](docs/案例库联调说明.md)：系统边界、数据开关、验收步骤和问题记录模板。
- [北大法宝 MCP 接入](docs/北大法宝MCP接入.md)：四个只读检索服务的环境变量配置与验收方式。
- [北大法宝 MCP 安装器](tools/pkulaw_mcp/README.md)：将安全的 MCP 配置合并进其他 Codex 项目，不接收或写入 Token。
- [飞书状态机联调 To-do](20260711-飞书状态机联调%20To-do.md)：飞书状态机侧待测项目。
- [飞书状态机所需内容](飞书状态机联调需要提供的内容.md)：审核请求和回写字段参考。

## 队友合并与下一步

本分支用于汇总当前代码、数据、测试和公开联调文档。合并前请至少执行：

```bash
python3 -m unittest discover -s tests -v
make pipeline
make audit-cases
```

合并后优先完成三项工作：

1. 以 `production_chunks.json` 为唯一生产索引，实现带输入校验和候选态隔离的 `/cases/retrieve` 服务适配层。
2. 补齐官方详情页来源并完成逐条人工审核，才允许候选案例迁入正式库。
3. 由部署环境安全注入接口凭证；仓库只保留变量名和无敏感值的示例配置。
