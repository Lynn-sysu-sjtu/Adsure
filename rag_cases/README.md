# Ads Penalty RAG（广告合规 AI 案例库）

面向广告合规审核的行政处罚案例库与规则 RAG 服务。仓库将官方处罚材料、待核验候选材料和规则引擎测试物料严格分开，提供可重复执行的导入、清洗、校验、切片、本地检索和多租户 HTTP 服务。

当前版本已完成离线数据流水线、Excel/DOCX 候选案例导入、行业候选切片、`/audit` 回归测试数据、飞书/法务工作台联调契约、可部署的 HTTP 检索服务、字段加权 BM25 与本地稠密向量混合召回，以及北大法宝 MCP 的安全配置。语义索引是仓库内可重建的本地文件，不依赖远程向量数据库。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 不访问网络，跑通样例抓取、清洗、校验、切片和检索
make pipeline

# 运行全部自动化测试
python3 -m unittest discover -s tests -v

# 需要混合召回时安装额外依赖并构建本地语义索引
pip install -r requirements-semantic.txt
make semantic-index
make evaluate-retrieval
```

默认流程只读取仓库内离线样例，不会发起真实网络请求。真实抓取必须先在 `data/sources/sources.yaml` 中人工填写官方详情页 URL，再显式执行 `python3 src/fetch_cases.py --allow-network`。

## 已交付能力

| 范围 | 实现 | 入口 |
| --- | --- | --- |
| 官方案例流水线 | 获取、正文提取、LLM/Mock 清洗、字段校验、RAG 切片 | `make pipeline` |
| 候选案例导入 | Excel 与行业 DOCX 导入；候选数据不进入生产库 | `make candidate-pipeline`、`make sector-candidate-pipeline` |
| 本地检索 | `case_summary` 与 `regulatory_logic` 两类切片，字段加权 BM25、稠密语义向量、RRF 混合排序、结构化过滤和空结果门槛 | `make evaluate-retrieval` |
| 案例检索 API | `POST /cases/retrieve`、`GET /health`、环境变量 Key 鉴权、生产/候选索引隔离；保留 `/search` 兼容路由 | `make serve` |
| 审核回归数据 | 20 条真实广告文案测试集及独立校验 | `make audit-cases` |
| Base v4 测试样例 | 按真实 58 字段快照生成 Base 字段记录和 `fields + rows` 批量写入载荷 | `data/audit_test_cases/base_v4_test_cases.json`、`base_v4_batch_create.json` |
| 联调设计 | 飞书状态机、规则引擎与案例库的请求、响应、边界与验收口径 | `docs/案例库接入接口确认稿.md` |
| 小红书聚光平台预检 | 独立、可版本化的平台规则目录，结构化证据与覆盖状态；当前仅为试点，默认不加载 | `POST /platform-rules/precheck`、`docs/小红书聚光平台规则预检实施方案.md` |
| 权威法律检索 | 项目级北大法宝 MCP 配置与可复用安装器；凭证仅由环境变量注入 | `docs/北大法宝MCP接入.md`、`tools/pkulaw_mcp/install.py` |

当前 production 已完整结构化同一市场监管总局公开页中的 10 起典型案例，
生成 20 个检索切片。公开页未披露具体法条编号，因此案例事实仍保留“广告法
有关规定”；系统另行提供待法律复核的适用条款映射，并明确标记为推定，不能
冒充处罚决定书明确引用。

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

# 安装语义依赖、重建语义索引并执行 lexical/hybrid 对照回归
make setup-semantic
make semantic-index
make evaluate-retrieval

# 构建并校验 /audit 测试集
make audit-cases

# 只运行本地检索
make test

# 启动生产索引接口（默认 127.0.0.1:8505）；Key 必须由部署环境注入
export ADSURE_API_KEY="<通过安全渠道生成的随机 Key>"
export CASE_ENGINE_INDEX_SCOPE="production"
export CASE_ENGINE_RETRIEVAL_MODE="hybrid"
make serve

# 运行 RAG API、租户隔离和空结果降级测试
make test-rag

# 小红书聚光平台规则模块（纯标准库测试）
make test-platform-rules

# 服务启动后执行健康检查和正式接口冒烟；凭证只从环境变量读取
make smoke-rag
```

`make audit-cases` 会保留标准 `/audit` 请求集，并额外生成与
“※审心广告物料合规审核台 v4”完全同名字段的 Base 测试记录。字段映射和
选项归一化规则见 [Base v4 测试样例字段映射](docs/Base%20v4测试样例字段映射.md)。

LLM 清洗支持 Mock、OpenAI 和 Anthropic：

```bash
python3 src/clean_cases.py --mode mock
python3 src/clean_cases.py --mode openai
python3 src/clean_cases.py --mode anthropic
```

将 `.env.example` 中的变量设置到本地环境即可。任何 API Key、Token、Cookie、内网地址或带凭证的调用示例都不得提交到仓库；缺少 LLM Key 时会安全回退到 Mock 模式。

## 当前系统边界

- 已实现本地文件流水线、字段加权 BM25、稠密语义向量、FastAPI `POST /cases/retrieve` 与 `GET /health`。`score_type`、`retrieval_method` 和 `similarity` 明确区分 BM25、语义余弦和混合融合分。
- `CASE_ENGINE_RETRIEVAL_MODE` 支持 `lexical`、`semantic`、`hybrid`。混合模式以 `fielded_bm25_v2` 和 `dense_semantic_v1` 的排序结果做加权 RRF 融合；BM25 负责精确命中，语义向量补充同义改写召回。
- 语义相似度低于 `CASE_ENGINE_MIN_SEMANTIC_SCORE` 时不进入候选集；字段 BM25 仍要求有效短语数和查询覆盖率，避免只有通用词也返回案例。
- 语义索引缺失、过期或模型加载失败时，服务显式报告 `semantic_status` 并降级到词法检索；设置 `CASE_ENGINE_REQUIRE_SEMANTIC=1` 可让生产预检直接失败。
- `/cases/retrieve` 向后兼容原请求，同时接受 `claim_spans`、`product_category`、`ad_channel`、`risk_dimensions` 和 `matched_rule_ids` 作为精度约束；无足够证据时返回空数组。
- `data/rules/advertising_law_2021.json` 保存现行广告法条款目录；案例的 `legal_basis_details` 同时返回条、款、项、版本、来源和映射审核状态。
- API Key 优先从 `ADSURE_API_KEY` 读取，并兼容旧的 `CASE_ENGINE_API_KEY`；默认索引范围为 `production`，候选联调必须显式设置 `CASE_ENGINE_INDEX_SCOPE=candidate`。
- 生产环境只能使用 `production_chunks.json`；候选索引仅可在隔离联调环境中显式启用，且必须返回候选态标记。
- 飞书法务工作台正式调用 `POST /cases/retrieve`；`POST /search` 仅作为已有多租户调用方的兼容路由保留，不是本轮飞书联调主契约。
- 正式召回在 BM25 打分前执行来源、审核状态和行业兼容过滤；生产索引为空时不回退候选库。
- 健康检查同时验证索引与服务端 Key 配置，响应携带脱敏请求追踪 ID 和索引版本。
- 实际访问官方页面时，必须遵守 `allowed_domains`、robots 和访问频率限制；不得绕过登录、验证码或调用非公开接口。
- 小红书平台规则与处罚案例索引隔离。当前目录状态为 `pilot_not_production`，正式模式只加载 `review_status=approved` 的规则；显式设置 `PLATFORM_RULES_ALLOW_PILOT=1` 仅允许在隔离试点环境执行候选规则。
- 平台规则命中只生成待人工复核的风险候选；缺少图片/OCR、落地页、场景或资质时返回覆盖不足，不得表述为“符合小红书规则”或“保证过审”。

## 项目结构

```text
src/                         流水线、导入器、校验器、切片与本地检索
tests/                       单元测试与端到端验收测试
data/sources/                官方来源配置与离线样例页面
data/raw_html/ raw_text/     原始材料和正文，按 case_id 保留
data/structured*/            正式、样例、归档和候选结构化案例
data/chunks*/                生产、候选、样例和测试切片索引
data/audit_test_cases/       与案例库隔离的 /audit 回归测试数据
data/schemas/                 Base 字段快照等可复现结构定义，不含既有业务记录
data/rules/                  现行法规条款目录与版本、来源信息
data/platform_rules/         平台规则公开来源短快照，与处罚案例原文隔离
data/evaluation/             人工维护的检索精度回归用例
data/reports/                校验、导入和选样报告
data/mappings/               候选案例到规则的映射建议
prompts/                     清洗、校验和检索测试提示词
docs/                        接口契约、联调说明和 MCP 接入说明
scripts/                     本地安全配置辅助脚本
tools/pkulaw_mcp/            可复用 MCP 配置安装与本地审计工具
.codex/config.toml           项目级 MCP 服务定义（不含任何凭证）
```

## 联调与文档入口

- [飞书前端 `/audit` v0.2 接口联调](docs/飞书前端-audit-v0.2接口联调.md)：请求映射、响应 schema、鉴权、路由和错误降级。
- [视频报告 → 飞书 v0.2 轮询接口](docs/视频报告转飞书v0.2轮询接口.md)：视频上传、任务轮询、幂等和 v0.2 结果取得。
- [RAG 服务部署与联调](docs/RAG服务部署与联调.md)：`/cases/retrieve`、`/health`、8505 部署和验收口径。
- [案例库接入接口确认稿](docs/案例库接入接口确认稿.md)：法务工作台正式 `/cases/retrieve` 契约。
- [案例库联调说明](docs/案例库联调说明.md)：系统边界、数据开关、验收步骤和问题记录模板。
- [北大法宝 MCP 接入](docs/北大法宝MCP接入.md)：四个只读检索服务的环境变量配置与验收方式。
- [北大法宝 MCP 安装器](tools/pkulaw_mcp/README.md)：将安全的 MCP 配置合并进其他 Codex 项目，不接收或写入 Token。
- [小红书聚光平台规则预检实施方案](docs/小红书聚光平台规则预检实施方案.md)：试点规则、接口契约、飞书字段提案与生产审批门。
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

1. 持续补齐官方详情页来源并完成逐条人工审核，才允许更多候选案例迁入正式库。
2. 将 `mapped_rule_ids` 的人工复核结果补回已核验案例。
3. 扩充人工标注的精排评测集，再决定是否引入 cross-encoder；当前只实现 BM25 + 稠密向量 RRF，不宣称已有生产准确率。
4. 由部署环境安全注入和轮换接口凭证；仓库只保留变量名和无敏感值的示例配置。

执行 `make rule-mapping-queue` 可生成正式案例人工映射队列；该队列只汇总已核验
证据，不自动猜测规则 ID 或具体法条。

部署前可执行 `ADSURE_API_KEY="<仅在当前 shell 注入>" make preflight-rag`。
正式索引为空、原文缺失、误启候选索引或 Key 缺失时预检会失败；systemd
服务也已配置相同的启动前阻断检查。

## 视频广告合规审核 MVP

本仓库包含独立的视频审核 MVP v3：上传 MP4/MOV/M4V 后，自动识别无字幕音轨，
进行基线与画面变化处加密抽帧、Apple Vision OCR、跨句/跨行规则匹配，
输出口播原文、时间戳、画面框、风险候选与必要展示项检查。转写或采样失败不会被包装成无风险。
新增本地中文双引擎、可授权的云端视觉语义、证明材料/活动条件/落地页一致性及平台来源状态核验。
使用前请阅读 [视频 MVP v3 验收与使用](docs/视频MVP-v3验收与使用.md)，v2 文档保留为历史记录。

```bash
# 首次安装：macOS + Python 3.12 + Xcode Command Line Tools
python3.12 -m venv .venv-video
.venv-video/bin/python -m pip install -r requirements-video.txt
.venv-video/bin/python -m src.video_mvp.asr --download-model medium
.venv-video/bin/python -m src.video_mvp.setup_models
# 之后只需启动；本机已有 .venv-video 和模型时不用重复安装
make video-mvp
# 浏览器打开 http://127.0.0.1:8510
```

也可不启动网页，直接分析本地视频：

```bash
VIDEO="/绝对路径/待审视频.mp4" \
OUTPUT="data/video_mvp/manual_run" \
INDUSTRY="保健食品" \
SAMPLE_INTERVAL="0.5" \
make video-mvp-cli
```

运行 `make test-video-mvp` 可验证 25 条正反例词面场景、跨句跨行、短暂画面、
失败降级、网页接口和证据链。这些是工程回归，不能当成实际广告识别准确率。
运行产物默认写入被忽略的 `data/video_mvp/jobs/` 或
`data/video_mvp/manual_run/`，不会修改或删除案例库的任何原始数据。

画面语义需要本机视觉模型，或在 `.env.video.local` 配置视觉 API 并逐任务勾选云端授权；不读取 `.env.example` 中的 Key。
证明材料只做文本和一致性检查，官方验真/真实功效/实际兑现、说话人分离、音乐授权、视频 DNA、IP 与字体版权仍未接通。
平台现有条款仍为待复核候选，不代表最新全量规则。抽帧未覆盖完整时长、
音轨识别失败或出现低置信度片段时，报告会明确降级覆盖状态。高置信度转写也可能错误；
`sampled_complete` 只表示配置下采样流程完成，不代表风险查全。所有结果固定为
`pending_human_review`，不构成违法认定、合规结论、法律意见或授权状态证明。

## Claude 交接包合流模块

两个 2026-09-08 交接目录经内容校验为同一份代码。合流后的唯一实现位于
`backend/app/`，不再从交接目录运行：

- `backend/app/crawler/` 将公开处罚材料只写入根目录
  `data/raw_html`、`data/raw_text` 与 `data/structured_candidates`；不会自动提升到
  `data/structured`，抓取地址必须为 HTTPS 且命中显式官方域名白名单。
- `backend/app/pipeline/`、`backend/app/rules/` 与 `backend/app/reasoning/` 作为可选的
  二次审核引擎，读取现有 `src/video_mvp` 产出的 `video-mvp-evidence/v1`，不替换
  当前视频 MVP v3。当前 ASR 的字词时间戳从 `raw_ref.words` 原样保留。
- 抓取配额写入 `data/ingest_runs/crawler_quota.json`，重启进程不会重置每小时上限。

```bash
# Python 3.12 隔离安装与回归测试
make setup-handoff
make test-handoff

# 不访问站点：用内置合成证据验证二次审核链路
make handoff-review-demo
# 输出：data/video_mvp/handoff_review.json；可拖入 frontend/review.html 查看

# 读取现有视频任务，不重跑 OCR/ASR
make handoff-review-job \
  VIDEO_JOB="data/video_mvp/jobs/<job_id>" \
  HANDOFF_OUTPUT="data/video_mvp/jobs/<job_id>/handoff_report.json"

# 案例 crawler：默认 mock 只验证抓取/存证边界，不产生可用结构化候选
make case-crawler CRAWLER_ARGS="--seed /绝对路径/seed.json --dry-run"
# 真实抽取必须显式选模型；结果仍为 pending_review
make case-crawler CRAWLER_ARGS="--seed /绝对路径/seed.json --llm deepseek --limit 8"
```

完整合流边界、验证证据与未验证事项见
[Claude 交接包合流说明](docs/Claude交接包合流说明.md)。
