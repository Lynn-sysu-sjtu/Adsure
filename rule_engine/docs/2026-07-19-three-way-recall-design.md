# 广告合规三路召回设计

## 目标

在保持 `/audit` 输入输出契约不变的前提下，将现有关键词/正则召回与智谱场景向量召回扩展为受控三路召回：关键词/正则、场景向量、LLM开放性规则目录。三路结果按父 `rule_id` 合并去重并裁剪出精简涵摄池，再交给现有 DeepSeek 完成规则内法律涵摄。

## 约束

- 正式修改仅发生在 `Adsure/rule_engine`。
- 飞书请求字段、响应顶层结构、中文业务字段和路由语义保持不变。
- 目录模型只能从给定规则目录选择真实 `rule_id`，不得判断违法、风险等级或生成新规则。
- 目录召回失败、超时或返回非法 JSON 时降级为空结果，不阻断关键词、向量和最终审核。
- 默认关闭目录召回；云端验证完成后通过环境变量开启。

## 架构

```text
本地关键词/正则召回
        │
        ├───────────────┐
        ▼               ▼
智谱场景向量召回    DeepSeek目录召回
        │               │
        └───────┬───────┘
                ▼
       按父rule_id合并去重
                ▼
       生成最多8条涵摄池
                ▼
         DeepSeek最终涵摄
```

fact规则继续进入现有补资料分支。完整召回结果继续用于 `matched_rules`、风险合成和路由；裁剪后的 `judgment_rule_pool` 仅作为DeepSeek涵摄输入，避免通过缩短提示词改变对外召回结果。

## 阶段一：去重与涵摄池裁剪

所有召回结果按 `rule_id` 去重。同一父规则由多渠道命中时保留一个规则对象并合并命中理由。涵摄池默认最多8条，排序优先级为：多路共同命中、目录命中、高分场景向量、强正则/关键词、fact补资料、弱泛化关键词。

`matched_rules`仍返回完整去重结果；DeepSeek只接收涵摄池。目录功能关闭时，24条既有content baseline的召回、维度和路由不得下降。

## 阶段二：开放性规则精简目录

目录不维护独立规则副本，而是从规则JSON的 `recall` 元数据生成：

```json
{
  "catalog_recall_enabled": true,
  "catalog_text": "侮辱物化消费者、恶俗价值观及违背良好风尚的营销表达",
  "catalog_group": "public_order_values"
}
```

首批目录仅包含：

- `GEN-PUBLIC-INTEREST-001`
- `GEN-SAFETY-PRIVACY-001`
- `GEN-GOOD-CUSTOMS-001`
- `GEN-OBSCENE-VIOLENCE-001`
- `GEN-DISCRIMINATION-001`
- `GEN-ENV-CULTURE-001`
- `GEN-MINOR-HEALTH-001`
- `GEN-MINOR-INDUCEMENT-001`

## 阶段三：受控目录召回

目录请求只包含物料上下文和精简目录。输出契约为：

```json
{
  "selected_rule_ids": ["GEN-GOOD-CUSTOMS-001"],
  "reason": "文案存在动物化羞辱消费者的表达"
}
```

最多选择3条。解析层过滤目录外ID、重复ID和超限结果。Mock后端用于单元测试；DeepSeek后端用于当前真实验证；接口预留智谱聊天模型后端。

## 阶段四：并发与降级

关键词召回本地同步完成。场景向量和目录召回使用两个工作线程并行执行。目录召回默认4秒超时；异常统一转为空结果。向量召回异常仍遵循现有API错误策略，不在本次改造中扩大降级范围。

## 配置

```text
ADSURE_CATALOG_RECALL_ENABLED=false
ADSURE_CATALOG_LLM_BACKEND=mock|deepseek|zhipu
ADSURE_CATALOG_LLM_MODEL=deepseek-chat
ADSURE_CATALOG_LLM_TIMEOUT=4
ADSURE_CATALOG_RECALL_LIMIT=3
ADSURE_JUDGMENT_POOL_LIMIT=8
```

## 契约与诊断

`/audit`不增加必需字段，不删除或改名现有字段。目录独立命中的规则使用 `recall_channel=llm_catalog`；同一规则多渠道命中时选择稳定主渠道并在内部保留渠道集合。新增诊断不进入飞书必需字段。

## 验收

- 目录关闭：现有单元测试通过，24条智谱＋Mock baseline保持召回、维度、路由24/24。
- 目录开启：目录只能返回白名单规则，异常可降级，三路父规则无重复。
- `CASE-SEM-006`继续只返回一个 `GEN-GOOD-CUSTOMS-001`父规则。
- `/audit`请求和既有响应字段保持不变。
- 比较目录开启前后的平均、P50、P95耗时、涵摄池大小、规则池外风险和风险一致率。
