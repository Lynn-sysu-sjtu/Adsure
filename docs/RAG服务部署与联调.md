# Adsure RAG 服务部署与联调

> 版本：v1.0
> 日期：2026-07-19
> 用途：飞书法务工作台类案联调
> 内部地址：`http://127.0.0.1:8505`

## 1. 已冻结接口

### `GET /health`

无需访问案例正文，只返回服务和当前索引状态：

```json
{
  "status": "ok",
  "service": "adsure-rag",
  "index_scope": "production",
  "candidate_data": false,
  "case_count": 10,
  "chunk_count": 20,
  "index_version": "16位索引摘要",
  "loaded_at": "UTC加载时间",
  "retrieval": {
    "requested_mode": "hybrid",
    "effective_mode": "hybrid",
    "semantic_status": "ready",
    "semantic_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
  },
  "checks": {
    "index": "ok",
    "api_key": "configured",
    "semantic": "ok"
  }
}
```

`status=degraded` 表示索引文件无法解析或服务端尚未配置 API Key。正式索引
合法但为空时服务仍存活，`case_count` 和 `chunk_count` 为 `0`。
语义索引缺失、过期或模型加载失败时，`checks.semantic=degraded`、
`effective_mode=lexical`；只要词法索引和 Key 可用，服务整体仍可为 `ok`。

### `POST /cases/retrieve`

请求头：

```text
Content-Type: application/json
X-API-Key: <由部署环境安全提供>
```

请求体：

```json
{
  "content": "普通食品宣称可以治疗高血压",
  "industry": "保健食品",
  "platform": ["抖音"],
  "claim_spans": ["治疗高血压"],
  "product_category": "普通食品",
  "ad_channel": "直播",
  "risk_dimensions": ["普通食品疾病治疗功效宣传"],
  "matched_rule_ids": ["ADLAW-017"],
  "top_k": 3
}
```

必填字段是 `content` 和 `industry`。其余结构化字段均可省略，以兼容旧调用方；
规则引擎能够提供时应传 `claim_spans`、产品类别、渠道、风险维度和规则 ID，
用于过滤错赛道结果。`top_k` 默认 3，允许 1—5。

成功响应：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "cases": [
      {
        "case_id": "case_xxx",
        "title": "案例名称",
        "risk_level": null,
        "violation_type": "虚假宣传",
        "risk_dimensions": ["履约风险"],
        "score": 0.991803,
        "score_type": "hybrid_rrf",
        "similarity": 0.742925,
        "source_name": "公开监管来源",
        "source_url": "https://example.gov.cn/case",
        "candidate_data": false,
        "content_snippet": "原案例广告宣称",
        "ruling": "处理结果",
        "regulatory_logic": "监管认定逻辑",
        "legal_basis": ["《中华人民共和国广告法》有关规定"],
        "mapped_rule_ids": ["ADLAW-017"],
        "legal_basis_details": [
          {
            "rule_id": "ADLAW-017",
            "article": "第十七条",
            "relation": "applicable_rule_inferred",
            "mapping_review_status": "pending_legal_review",
            "source_url": "https://www.samr.gov.cn/..."
          }
        ],
        "retrieval_method": "hybrid_rrf_v1",
        "match_evidence": {
          "matched_terms": ["治疗", "高血", "血压"],
          "matched_fields": ["illegal_claims", "regulatory_logic"],
          "query_coverage": 0.75,
          "lexical_score": 8.23,
          "semantic_similarity": 0.742925,
          "fusion_score": 0.991803
        }
      }
    ],
    "retrieval_meta": {
      "index_scope": "production",
      "index_version": "16位索引摘要",
      "top_k": 3,
      "returned": 1
    }
  }
}
```

`score` 的含义由 `score_type` 决定：词法模式是 BM25 原始分，语义模式是余弦，
混合模式是 RRF 融合分。三者都不是风险百分比。只有结果实际进入语义候选集时，
`similarity` 才返回真实语义余弦，否则为 `null`。RAG 只返回结构化案例事实，
不输出整段最终法律意见。`risk_level` 当前没有稳定案例字段，固定返回 `null`。

服务同时执行有效短语数、查询覆盖率和相对分数门槛，因此实际返回数可以少于
`top_k`，也可以为 0。覆盖率阈值由 `CASE_ENGINE_MIN_QUERY_COVERAGE` 调整，
相对分数阈值由 `CASE_ENGINE_MIN_RELATIVE_SCORE` 调整，取值范围均为 0—1。

`legal_basis` 只表示案例来源实际披露的依据。`legal_basis_details` 中
`relation=applicable_rule_inferred` 的具体条款是根据官方摘要事实作出的适用性
映射；在 `mapping_review_status` 完成法律复核前，不得表述为处罚决定书明确引用。

行业过滤在任何检索打分前执行。游戏和美妆请求不会因“虚假宣传”等通用词命中
其他行业案例；保健食品请求允许召回健康产品和普通食品中的疾病功效宣传案例，
但返回值保留案例的原始行业。

无相关案例返回 HTTP 200：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "cases": [],
    "retrieval_meta": {
      "index_scope": "production",
      "index_version": "16位索引摘要",
      "top_k": 3,
      "returned": 0
    }
  }
}
```

请求字段或 JSON 格式错误返回 HTTP 400，鉴权失败返回 HTTP 401。服务未配置
Key、索引损坏或检索内部异常返回 HTTP 503、`code=-1` 和
`data={"cases":[]}`，由工作台后端记录异常并降级为空态。

所有 HTTP 响应都带 `X-Request-ID`。调用方提供合法的 `X-Request-ID` 时服务
原样返回，否则自动生成。日志仅记录请求 ID、路径、状态码、耗时和索引版本，
不记录物料正文或 API Key。

## 2. 调用方式与数据范围

本轮采用独立 HTTP 服务，不采用飞书项目直接 import 本仓库 Python 模块的
进程内调用。这样可以独立部署、鉴权、健康检查和降级，飞书侧只需配置
`CASE_ENGINE_URL` 与 `CASE_ENGINE_API_KEY`。

`/cases/retrieve` 不接收 `tenant_id`，只召回 `scope=public` 的已核验正式
案例。仓库保留的 `/search` 路由支持租户隔离，但它是兼容能力，不属于本轮
飞书契约；需要企业私有案例时应另行冻结升级契约。

## 3. 正式库与候选库

默认配置：

```text
CASE_ENGINE_INDEX_SCOPE=production
```

正式模式只读取 `data/chunks/production_chunks.json`，索引为空时不自动回退
候选库。候选数据只能在隔离演示环境显式启用：

```text
CASE_ENGINE_INDEX_SCOPE=candidate
```

候选模式响应始终带有 `candidate_data=true` 和来源核验状态。候选材料不得
被展示为已经核实的处罚事实。

## 4. 本地启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-semantic.txt
make semantic-index
export ADSURE_API_KEY="<仅在当前 shell 注入>"
export CASE_ENGINE_INDEX_SCOPE="production"
export CASE_ENGINE_RETRIEVAL_MODE="hybrid"
export CASE_ENGINE_MIN_SEMANTIC_SCORE="0.62"
export CASE_ENGINE_EMBEDDING_ALLOW_DOWNLOAD="0"
make serve
```

默认禁止服务运行时下载模型。部署前应通过受控流程准备模型缓存；若只安装
`requirements.txt`，将 `CASE_ENGINE_RETRIEVAL_MODE=lexical`。混合模式下语义
资源不可用会降级到词法；需要将语义能力作为启动硬门禁时再设置
`CASE_ENGINE_REQUIRE_SEMANTIC=1`。

systemd 示例启用了 `ProtectHome=true`，因此不要依赖部署账号主目录中的模型
缓存。将完整模型缓存放到 `/opt/adsure-rag/models`，并使用示例配置中的
`HF_HOME`、`HF_HUB_OFFLINE=1` 和 `TRANSFORMERS_OFFLINE=1`。

验证：

```bash
curl -s http://127.0.0.1:8505/health

curl -s \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADSURE_API_KEY" \
  -d '{
    "content": "保健食品宣称预防和治疗疾病",
    "industry": "保健食品",
    "platform": ["抖音"],
    "top_k": 3
  }' \
  http://127.0.0.1:8505/cases/retrieve
```

命令不会打印 Key。不要把真实 Key 写进脚本、文档、Git 或工单。

## 5. 8505 部署

仓库提供：

- `deploy/systemd/adsure-rag.service`
- `deploy/rag.env.example`

建议安装目录为 `/opt/adsure-rag`，非敏感配置保存到
`/etc/adsure/rag.env`，真实 `ADSURE_API_KEY` 单独保存在权限为 `0600` 的
`/etc/adsure/rag-secret.env`：

```text
ADSURE_API_KEY=<真实随机值>
```

安装后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now adsure-rag
sudo systemctl status adsure-rag
curl -s http://127.0.0.1:8505/health
```

systemd 在每次启动前都会运行生产预检，并自动读取上述两个
`EnvironmentFile`。预检失败时可通过
`sudo journalctl -u adsure-rag -n 50 --no-pager` 查看不含密钥和案例正文的
错误摘要。以下任一情况会阻止服务启动：

- `CASE_ENGINE_INDEX_SCOPE` 不是 `production`；
- 未配置 `ADSURE_API_KEY`；
- 正式索引为空、损坏或切片找不到结构化案例；
- 案例不满足 production 入库门禁；
- 案例声明的 `raw_text_path` 在部署目录中不存在；
- 正式索引中没有可供 `/cases/retrieve` 使用的公共案例。

当 `CASE_ENGINE_REQUIRE_SEMANTIC=1` 时，语义索引缺失、与切片指纹不一致或模型
无法加载也会阻止启动；默认值为 `0`，此时预检记录实际模式并允许词法降级。

预检只输出数量、索引版本和错误类型，不输出 API Key 或案例正文。本地使用与
systemd 相同环境变量时也可以执行 `make preflight-rag`。

部署后使用自动冒烟脚本验证健康状态、生产索引范围、鉴权和正式接口契约：

```bash
export CASE_ENGINE_URL="http://127.0.0.1:8505"
export CASE_ENGINE_API_KEY="<通过安全渠道取得>"
make smoke-rag
```

脚本不会输出 Key，也不会要求检索必须命中案例；正式库为空时仍可验证接口
契约。`CASE_ENGINE_URL` 固定为不带 `/cases/retrieve` 的 Base URL。

8505 仅监听 `127.0.0.1`，由同机统一审核 API 调用，不直接暴露给飞书或公网。
统一审核 API 对 RAG 应设置短超时，并在超时、网络错误或非成功响应时写入
`related_cases=[]`，保留规则审核结果。

## 6. 验收命令

```bash
make chunks
make semantic-index
make evaluate-retrieval
ADSURE_API_KEY="<仅在当前 shell 注入>" make preflight-rag
make test-rag
python3 -m unittest discover -s tests -v
```

自动化覆盖：

1. 正式接口返回工作台所需案例字段；
2. 空生产索引不回退到候选库；
3. 无关查询返回 HTTP 200 和空数组；
4. 损坏索引返回 HTTP 503，健康状态为 `degraded`；
5. 未配置 API Key 时健康状态为 `degraded`；
6. 响应包含请求追踪 ID 和稳定索引版本；
7. API Key、JSON/字段校验、候选库显式标记和 `/search` 兼容路由；
8. 语义同义改写召回、负例空结果、混合索引指纹和词法降级。

`data/evaluation/retrieval_quality_cases.json` 是小规模人工回归集，只用于防止
已知问题复发。报告中的通过率不能表述为全量生产准确率；扩大正式案例库后应
补充盲测集并单独统计 Recall@K、Precision@K 和无关查询拒答率。
