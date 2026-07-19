# Adsure 三模块接口契约草案

> 状态：草案，未冻结  
> 更新时间：2026-07-19  
> 目的：记录规则引擎已经确认的行为、当前飞书代码观察结果，以及 RAG 接口建议。标记为“明日确认”的内容需由飞书/RAG 负责人确认后再冻结。

## 1. 当前服务边界

```text
飞书状态机
  -> 规则引擎 POST /audit
  -> 当前直接把规则结果写回多维表格

统一编排服务（本次新增骨架，尚未接入飞书）
  -> 规则引擎 POST /audit
  -> RAG POST /search（当前使用 Mock，真实服务待 RAG 负责人实现）
  -> 合并 related_cases
```

当前规则引擎地址由飞书侧 `RULE_ENGINE_URL` 配置，云端已使用过的端口为 `8504`。正式地址以部署环境为准。

## 2. 规则引擎接口

### 2.1 地址与鉴权

```http
POST /audit
X-API-Key: <ADSURE_API_KEY>
Content-Type: application/json
```

健康检查：

```http
GET /health
```

`/health` 不要求业务 API Key，不调用 DeepSeek、智谱、规则加载或向量索引。

响应：

```json
{
  "status": "ok",
  "service": "adsure-rule-engine",
  "version": "0.1.0"
}
```

### 2.2 当前飞书扁平请求

飞书当前在 `feishu_state_machine/predictor.py:215` 的 `call_teammate_engine()` 中发送：

```json
{
  "record_id": "rec_xxx",
  "industry": "游戏",
  "content": "充3元送一只狗",
  "platform": ["抖音"],
  "material_type": "Banner",
  "product_category": "游戏",
  "urgency": "普通",
  "supplement": "",
  "extras": {
    "游戏名称": "示例游戏"
  },
  "mode": "标准"
}
```

字段说明：

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `record_id` | string | 当前飞书必填 | 多维表格记录 ID，同时映射为 `request_id` |
| `industry` | string | 是 | `美妆 / 游戏 / 保健食品 / 通用` |
| `content` | string | 是 | 广告物料正文；关键词/正则只匹配该字段 |
| `platform` | string[] | 否 | 投放平台，上下文和语义召回可使用 |
| `material_type` | string | 否 | Banner、短视频、直播话术等 |
| `product_category` | string | 否 | 产品品类 |
| `urgency` | string | 否 | 普通、紧急等 |
| `supplement` | string | 否 | 运营补充背景资料 |
| `extras` | object | 否 | 行业专属字段 |
| `mode` | string | 否 | 当前 MVP 最终统一为标准模式 |
| `tenant_id` | string | 否 | 当前默认 `adsure_demo`，只透传，不启用多租户逻辑 |

### 2.3 内部标准请求

规则引擎现在兼容下列与飞书字段解耦的结构：

```json
{
  "tenant_id": "adsure_demo",
  "request_id": "rec_xxx",
  "source": "feishu",
  "material": {
    "material_id": "M001",
    "content": "充3元送一只狗",
    "attachments": [],
    "submitter": "",
    "submitted_at": null,
    "urgency": "普通",
    "supplemental_background": ""
  },
  "context": {
    "industry": "游戏",
    "material_type": "Banner",
    "platforms": ["抖音"],
    "product_category": "游戏",
    "product_filing_name": "",
    "approval_or_filing_number": "",
    "core_claims": [],
    "scenario": "",
    "game_name": "示例游戏",
    "ip_name": ""
  },
  "audit": {
    "requested_mode": "标准"
  }
}
```

兼容规则：

- `tenant_id` 缺失时默认 `adsure_demo`。
- 显式传入的 `tenant_id` 原样透传到响应。
- 未知顶层字段不进入标准内部请求，不影响审核。
- `record_id` 在旧飞书请求中映射为 `request_id`。
- 旧扁平请求继续兼容，不要求飞书立即改造。

### 2.4 成功响应

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "tenant_id": "adsure_demo",
    "request_id": "rec_xxx",
    "resolved_mode": "标准",
    "mode_reason": "MVP阶段统一使用标准审核模式，极速和深度模式仅预留接口。",
    "预审_风险等级": "中",
    "预审_命中要点": "命中规则：……",
    "预审_修改建议": "……",
    "预审_时间": 1784390000000,
    "审核_审核意见": "意见类型：风险提示\n……",
    "审核_关键实体抽取": "游戏、抖音",
    "审核_高风险词命中": "命中规则：……",
    "审核_平台规则预检": "……",
    "审核_备案核查结果": "……",
    "审核_推荐违规类型": ["虚假宣传"],
    "审核_推荐风险等级": "中",
    "risk_assessment": {},
    "matched_rules": [],
    "semantic_recall": {},
    "rule_judgments": [],
    "llm_judgment": {},
    "context_package": {},
    "routing": "运营",
    "审核_审核时间": 1784390000000,
    "audit_time": 1784390000000
  }
}
```

### 2.5 失败响应

输入校验或内部错误均保持 HTTP 可解析 JSON：

```json
{
  "code": -1,
  "msg": "缺少必填字段：①运营·物料内容",
  "data": null
}
```

当前飞书侧在 `predictor.py:240` 检查 `code != 0` 后抛出异常，由 `bot_listener.py:145` 的执行链捕获并回退状态。

## 3. 枚举

### 3.1 routing

规则引擎返回：

| 值 | 飞书当前映射 |
|---|---|
| `运营` | `待运营修改` |
| `法务` | `待法务复核` |

飞书当前映射代码位于 `predictor.py:248` 的 `_decide_routing()`。

### 3.2 opinion_type

LLM 输出必须四选一：

| 值 | 含义 |
|---|---|
| `风险提示` | 目前不能直接认定投放前违法，但存在履约、证明或披露风险 |
| `违规修改` | 文案本身触发刚性规则，投放前应修改 |
| `需补资料` | 缺少证明材料或业务事实，暂时不能完成判断 |
| `无明显风险` | 未发现明显规则命中 |

当前 `opinion_type` 位于 `data.llm_judgment.opinion_type`，同时会作为“意见类型：…”前缀写入 `审核_审核意见`。飞书当前不设置独立字段。

## 4. matched_rules 结构

规则引擎当前每条命中规则包含：

```json
{
  "rule_id": "GAME-AD-002",
  "rule_uid": "…",
  "serial_no": 2,
  "title": "广告中附带赠送应当明示品种、规格、数量、期限和方式",
  "dimension": "虚假宣传",
  "risk_level": "中",
  "judgment": "初步命中",
  "match_reason": "命中规则：广告中附带赠送应当明示……",
  "raw_hit_terms": [],
  "recall_channel": "keyword",
  "legal_basis": [],
  "legal_basis_detail": [],
  "semantic_criteria": null,
  "decision": null,
  "applies_to": {},
  "preconditions": {},
  "rule_nature": null,
  "routing": {},
  "legal_attention": {},
  "review_required": null,
  "source_type": "法规",
  "platform": null,
  "trigger_layer": "content"
}
```

`recall_channel` 当前枚举：`keyword / semantic / fact`。

面向用户的展示不得使用 `raw_hit_terms` 暴露弱触发词或正则表达式。用户主要查看规则标题、风险维度和法条原文。

## 5. legal_basis_details 说明

当前规则引擎没有独立的顶层 `legal_basis_details` 字段。当前等价数据位于：

```text
matched_rules[].legal_basis_detail
```

单条法律依据示意：

```json
{
  "source_id": "AL",
  "article": "第八条",
  "legal_level": 1,
  "role": "based_on",
  "text": "广告中表明推销的商品或者服务附带赠送的……"
}
```

`source_type` 位于命中规则层，`legal_basis_detail` 的单条依据使用 `source_id/article/legal_level/role/text`。其中 `legal_level` 映射：

```text
1 = 法律
2 = 行政法规
3 = 部门规章
4 = 规范性文件/国家标准/监管指引
null + source_type=平台规则 = 平台规则
```

法条原文和中文效力层级目前已经由规则引擎格式化并追加到 `审核_审核意见` 的“触犯法条原文”部分。

**明日确认：** 是否需要统一服务额外派生独立的 `legal_basis_details`，供 Web 工作台折叠展示；飞书现有字段不依赖该顶层字段。

## 6. RAG /search 建议契约

当前 `rag_cases` 已有数据流水线和本地检索，但尚无可部署 HTTP 服务。本节是建议契约。

### 6.1 请求

```http
POST /search
Content-Type: application/json
```

```json
{
  "tenant_id": "adsure_demo",
  "query": "充3元送一只狗",
  "industry": "游戏",
  "matched_rules": [
    {
      "rule_id": "GAME-AD-002",
      "dimension": "虚假宣传"
    }
  ],
  "top_k": 3
}
```

### 6.2 成功响应

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "cases": [
      {
        "case_id": "case_001",
        "title": "赠送活动未兑现案例",
        "summary": "广告承诺赠品但未实际提供",
        "source": "公开监管案例",
        "similarity": 0.82
      }
    ]
  }
}
```

空结果必须是成功响应：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "cases": []
  }
}
```

## 7. 统一编排服务

本次新增骨架：

```http
POST /api/v1/audits
GET /health
```

流程：

```text
接收内部标准请求
-> 调用规则引擎 /audit
-> 规则引擎失败：原样返回，不调用 RAG
-> 规则引擎成功：根据 content、industry、matched_rules 调用 RAG
-> 合并 related_cases 和 case_search_status
```

RAG 正常且有结果：

```json
{
  "related_cases": [{"case_id": "case_001"}],
  "case_search_status": "ok"
}
```

RAG 正常但无结果：

```json
{
  "related_cases": [],
  "case_search_status": "empty"
}
```

RAG 超时、网络异常、非零 code 或结构异常：

```json
{
  "related_cases": [],
  "case_search_status": "unavailable"
}
```

RAG 是增强链路，其失败不得覆盖规则引擎已经生成的审核结果。

## 8. 当前飞书调用链代码观察

本节只记录当前基线，不代表明日终版。

### 8.1 调用位置

- `predictor.py:215`：`call_teammate_engine()`。
- `predictor.py:224`：使用 `requests.post()` 调用 `RULE_ENGINE_URL`。
- 请求头：`X-API-Key`、`Content-Type: application/json`。
- 超时：10 秒。
- `predictor.py:453`：`execute()` 调用规则引擎。
- 若返回 dict 且含 `routing`，直接使用规则引擎结果，跳过飞书侧本地 LLM。

### 8.2 当前读取的响应字段

飞书回写直接消费：

```text
resolved_mode
mode_reason
预审_风险等级
预审_命中要点
预审_修改建议
审核_审核意见
审核_关键实体抽取
审核_高风险词命中
审核_平台规则预检
审核_备案核查结果
审核_推荐违规类型
审核_推荐风险等级
routing
audit_time
```

`matched_rules` 当前不会作为单独飞书字段写回；规则引擎已将命中规则和法条原文拼入 `审核_审核意见`。

### 8.3 当前写回字段

`predictor.py:388` 的 `write_back()` 写回：

```text
②AI预审·风险等级
②AI预审·命中要点
②AI预审·修改建议
②AI预审·时间
③AI审核·审核模式
③AI审核·模式推荐理由
③AI审核·审核意见
③AI审核·关键实体抽取
③AI审核·高风险词命中
③AI审核·平台规则预检
③AI审核·备案核查结果
③AI审核·推荐违规类型
③AI审核·推荐风险等级
③AI审核·审核时间
⑤流转·当前状态
```

具体字段常量以 `feishu_state_machine/fields_v4.py` 为准。

### 8.4 当前卡片展示

`bot_listener.py:234` 运营结果卡片读取：

```text
预审_风险等级
预审_命中要点
预审_修改建议
```

并提供查看审核意见、修改物料、重新提交和升级法务按钮。

`bot_listener.py:283` 法务通知卡片读取：

```text
预审_风险等级
预审_命中要点
物料内容预览
```

并提供法务工作台链接。

当前卡片没有直接展示 RAG 类案。

### 8.5 法务工作台展示

`app.py:443` 附近的 `normalize_record()` 将飞书字段转换为工作台前端结构，包含 AI 审核意见、关键实体、高风险词、平台规则、备案核查、违规类型、风险等级和法务裁决字段。

当前没有 `related_cases` 对应的多维表格字段或工作台字段。

## 9. 明日待负责人确认

请飞书负责人对每项标记：`保持不变 / 已修改 / 准备废弃`。

1. `call_teammate_engine()` 是否仍位于 `predictor.py`。
2. 当前扁平请求字段是否继续使用。
3. 飞书是否直接调用规则引擎，还是改为统一服务 `/api/v1/audits`。
4. 10 秒规则引擎超时是否调整。
5. `write_back()` 的 ②③ 段字段是否保持不变。
6. RAG 类案展示位置：审核意见正文、法务工作台独立区域，或新增飞书字段。
7. 法务和运营卡片是否需要展示“相关类案”入口。
8. 哪些飞书文件仍在修改，避免多人同时编辑。

请 RAG 负责人确认：

1. 是否接受 `/search` 请求结构。
2. `cases[]` 的正式字段。
3. 是否能稳定返回 `case_id/title/summary/source/similarity`。
4. 无结果和异常时的响应策略。
5. 第一版采用 HTTP 服务还是进程内 Python 调用。

## 10. 当前不做

- 不修改飞书状态机文件。
- 不让飞书立即切换统一服务。
- 不建设真实多租户隔离。
- 不新增飞书多维表格字段。
- 不因 RAG 失败中断规则审核。
