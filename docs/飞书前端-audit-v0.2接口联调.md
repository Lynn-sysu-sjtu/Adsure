# 飞书前端 `/audit` v0.2 接口联调

更新：2026-09-12。后端已在案例检索主服务中增加 `POST /audit`，响应与飞书提供的 `audit_response_schema_v0.2` 对齐。该接口返回规则风险候选和路由建议，不是违法认定或自动投放许可。

## 地址与鉴权

```text
POST <RULE_ENGINE_URL>/audit
Content-Type: application/json
X-API-Key: <由部署环境安全注入>
X-Request-ID: <可选链路 ID>
```

本机默认由 `make serve` 启动在 `http://127.0.0.1:8505`。`RULE_ENGINE_URL` 填 Base URL，不要重复拼接两次 `/audit`。服务端从 `ADSURE_API_KEY` 读取凭据；不要把真实 Key 写入仓库、飞书脚本日志或截图。

健康检查 `GET /health` 的 `audit_contract.response_schema` 应为 `audit_response_v0.2`。健康检查不需要把 API Key 放入 URL。

## 推荐请求

```json
{
  "record_id": "rec_xxx",
  "mode": "标准",
  "industry": "美妆",
  "content": "15天见效，全网第一",
  "urgency": "普通",
  "supplement": "",
  "platform": ["小红书"],
  "material_type": "图文",
  "product_category": "护肤",
  "extras": {
    "产品备案名称": "示例名称",
    "核心宣称功效": ["美白"]
  }
}
```

为适配现有飞书前端，也接受 Base v4 包装：

```json
{
  "record_id": "rec_xxx",
  "mode": "标准",
  "fields": {
    "①运营·行业领域": "美妆",
    "①运营·物料内容": "15天见效，全网第一",
    "①运营·紧急程度": "普通",
    "①运营·补充背景资料": "",
    "①美妆·物料类型": "图文",
    "①美妆·投放平台": ["小红书"],
    "①美妆·产品品类": "护肤",
    "①美妆·产品备案名称": "示例名称"
  }
}
```

前端应始终传完整物料，不要只传疑似违规片段；`human_reference` 和 `provenance` 是离线答案/来源字段，线上请求会拒绝，避免测试答案泄漏。

## 成功响应保证

- 顶层固定为 `code`、`msg`、`data`，成功时 `code=0`。
- `data.request_id` 原样回传 `record_id`，供飞书幂等校验。
- `预审_时间`、`审核_审核时间`、`audit_time` 是同一个毫秒时间戳。
- `审核_推荐违规类型` 始终是字符串数组。
- `审核_推荐风险等级` 只返回 `高/中/低`；无规则命中时，只有 `预审_风险等级` 返回 `无明显风险`，法务推荐为 `低`。
- `matched_rules` 每项必含 `rule_id/title/dimension/risk_level/judgment/match_reason/default_routing`。
- `default_routing` 只返回 `运营/法务/运营补资料`。任一规则为法务时顶层 `routing=法务`；补资料通过规则项传递，顶层仍按 v0.2 只返回 `运营/法务`。
- 高风险词使用原文词面，不返回 `regex:...`。
- 未接入备案、版号官方验真时只返回“待核查”，不会把格式或真实性写成已通过。

`applicability_status` 目前统一为 `needs_fact_verification`。即使命中“国家级”“治疗”等文字，也还需要判断广告属性、产品类别、完整语境、例外和证据，不输出 `confirmed_violation`。

失败时返回稳定包络：

```json
{"code":-1,"msg":"具体错误原因","data":null}
```

飞书侧可按现有逻辑将 `code != 0`、HTTP 超时或网络失败作为引擎失败，不写审核字段并回退“运营起草”。

## Schema 文件说明

飞书传来的原文件在多处 description 中直接使用未转义半角双引号，严格 JSON 解析会在第 4 行失败。仓库中的[可执行副本](../data/schemas/audit_response_v0.2.schema.json)只修复这些描述文字的 JSON 引号，没有改变 required、enum、字段类型或 `additionalProperties` 约束。

## 本地验证

```bash
cd "/Users/lcdat/Documents/广告合规AI"
make test-audit-contract
python3 -m unittest tests.test_api
```

可用占位 Key 做本机联调；不要把生产 Key 写进命令历史：

```bash
export ADSURE_API_KEY="<通过安全渠道注入>"
make serve
```

联调请求示例：

```bash
curl -sS http://127.0.0.1:8505/audit \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $ADSURE_API_KEY" \
  --data-binary @request.json
```

本地单元测试只能证明接口序列化、鉴权、输入映射、规则候选和错误降级。真实飞书按钮、网络地址、超时、卡片通知、Base 回写、多选枚举是否已配置，以及最终状态流转，仍需在飞书测试环境完成一次端到端联调。
