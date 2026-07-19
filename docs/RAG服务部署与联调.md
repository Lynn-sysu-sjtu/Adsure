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
  "checks": {
    "index": "ok",
    "api_key": "configured"
  }
}
```

`status=degraded` 表示索引文件无法解析或服务端尚未配置 API Key。正式索引
合法但为空时服务仍存活，`case_count` 和 `chunk_count` 为 `0`。

### `POST /cases/retrieve`

请求头：

```text
Content-Type: application/json
X-API-Key: <由部署环境安全提供>
```

请求体：

```json
{
  "content": "充3元送一只狗",
  "industry": "游戏",
  "platform": ["抖音"],
  "top_k": 3
}
```

必填字段是 `content` 和 `industry`。`platform` 缺省为 `[]`；`top_k`
默认 3，允许 1—5。飞书工作台不需要传 `tenant_id`、命中规则或审核结论。

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
        "score": 8.23,
        "source_name": "公开监管来源",
        "source_url": "https://example.gov.cn/case",
        "candidate_data": false,
        "content_snippet": "原案例广告宣称",
        "ruling": "处理结果",
        "regulatory_logic": "监管认定逻辑",
        "legal_basis": ["《中华人民共和国广告法》"]
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

`score` 是 BM25 原始排序分，不是百分比或 embedding 语义相似度。RAG 只返回
结构化案例事实，不输出整段最终法律意见。`risk_level` 当前没有稳定案例字段，
固定返回 `null`，不得根据排序分推导。

服务默认只保留分数不低于第一名 25% 的结果，因此实际返回数可以少于 `top_k`，
不会为了凑满数量展示明显偏弱的长尾案例。阈值可通过
`CASE_ENGINE_MIN_RELATIVE_SCORE` 调整，取值范围为 0—1。

行业过滤在 BM25 打分前执行。游戏和美妆请求不会因“虚假宣传”等通用词命中
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
pip install -r requirements.txt
export ADSURE_API_KEY="<仅在当前 shell 注入>"
export CASE_ENGINE_INDEX_SCOPE="production"
make serve
```

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
7. API Key、JSON/字段校验、候选库显式标记和 `/search` 兼容路由。
