# 涵摄上下文溯源与行业适用边界设计

## 目标

修复两个内部数据流问题：

1. `①运营·补充背景资料` 已进入语义召回，但没有进入 DeepSeek 涵摄上下文；
2. `①运营·行业领域` 本应主要用于召回限定和流转路由，但 DeepSeek 可能将它当成产品法律属性已经确认的证据。

修复后，普通果汁宣称治疗癌症的案例应保留《广告法》第十七条的直接内容违规，但不得仅因飞书行业字段填为“保健食品”，就确认保健食品专属标签、说明书和广告规则适用。

## 兼容性约束

- `/audit` 请求字段不变；
- `/audit` 响应字段和已有 `context_package` 结构不变；
- 飞书字段名称、状态机、风险合成和路由输出不变；
- 关键词召回仍只使用物料原文；
- 语义召回仍使用文案、补充背景和结构化上下文；
- 行业字段仍可以用于限制候选池，防止全行业规则噪声膨胀。

## 架构设计

### 1. 保留现有公开上下文

`build_context_package(request)` 保持现有返回结构，继续用于：

- 公开 `/audit` 响应；
- 风险合成、路由和展示；
- 现有调试与兼容性测试。

不向该对象新增字段，避免对外契约产生隐性变化。

### 2. 新增涵摄专用上下文

新增内部函数：

```python
build_judgment_context_package(request, public_context_package)
```

该对象只传给 DeepSeek，不写入 `/audit` 对外响应。它在现有上下文基础上增加：

```json
{
  "supplemental_background": "运营填写的补充背景",
  "context_provenance": {
    "material_text": "advertising_content",
    "supplemental_background": "operator_supplied_unverified",
    "industry": "recall_and_routing_label",
    "product_category": "operator_structured_unverified"
  },
  "context_conflicts": []
}
```

信任边界：

- `material_text` 是待审核广告原文，可用于内容构成要件和连续证据；
- `supplemental_background` 可用于理解产品和发现冲突，但不得单独作为 `confirmed_violation` 的已核验事实；
- `industry` 是召回与路由标签，不能单独证明产品法律属性；
- `product_category` 是运营提交的结构化信息，比自由文本稳定，但在资质冲突时仍需核验。

### 3. 通用冲突检测

本次不枚举所有普通食品和保健食品品类，只检测补充背景对当前行业的显式否定：

```text
行业领域 = 保健食品
补充背景包含 = 非保健食品
```

生成：

```json
{
  "type": "declared_industry_denied_by_background",
  "declared_industry": "保健食品",
  "background_evidence": "非保健食品",
  "verification_required": true
}
```

冲突只证明产品身份需要核验，不证明补充背景一定正确。

### 4. DeepSeek 涵摄政策

向 `judgment_policy` 增加：

- 上下文来源和信任等级说明；
- 行业字段不构成产品法律身份的证明；
- 显式冲突存在时，依赖该产品身份的行业专属规则不得仅凭行业标签判为 `confirmed_violation`；
- 不依赖产品身份的通用内容禁止规则可继续直接判断；
- 补充背景只能触发事实核验、适用性排除或人工注意，不得单独作为已核验违法事实。

提示词增加边界示例：

```text
文案：治疗肝癌、肺癌等癌症
行业标签：保健食品
补充背景：普通果汁饮品，非保健食品

通用非医疗广告涉及疾病治疗规则：confirmed_violation
保健食品专属身份规则：不得仅凭行业标签确认，根据规则要件返回 needs_fact_verification 或 not_applicable
```

### 5. 确定性涵摄保护

仅修改提示词不足以对抗模型波动，因此增加内部后处理函数：

```python
apply_context_provenance_guard(rule_judgments, candidate_rules, judgment_context)
```

仅当同时满足以下条件时介入：

1. `context_conflicts` 存在显式行业否定；
2. LLM 将规则判为 `confirmed_violation`；
3. 候选规则的 `applies_to.industries` 只面向被否定的行业，不包含“通用”；
4. 规则适用依赖该产品身份。

保护行为：

- 将该行业专属规则降为 `needs_fact_verification`；
- `missing_facts` 补充“核验产品是否属于声明行业及相应资质”；
- 保留通用内容违规判断；
- 不改变候选召回结果和父规则去重结果。

如候选规则未声明行业范围或包含“通用”，保护器不介入，避免错误降级《广告法》第十七条、良好风尚等通用内容规则。

## 数据流

```text
飞书原始字段
   │
   ├─ 文案原文 ─────────→ 关键词召回
   │
   ├─ 文案+补充背景+结构字段 → 智谱语义召回
   │
   └─ 公开上下文
          └─ 涵摄专用上下文
                ├─ 补充背景（未核验）
                ├─ 行业标签（召回/路由）
                └─ 显式冲突
                       ↓
                    DeepSeek涵摄
                       ↓
               确定性上下文保护
                       ↓
                 现有风险合成与/audit响应
```

## 测试设计

### 上下文单元测试

- 涵摄专用上下文包含完整 `supplemental_background`；
- 补充背景来源为 `operator_supplied_unverified`；
- 行业字段角色为 `recall_and_routing_label`；
- 现有公开 `context_package` 结构不变。

### 冲突检测测试

- `行业=保健食品 + 背景=非保健食品` 生成冲突；
- 没有显式否定时不生成冲突；
- 只有“普通果汁饮品”而无“非保健食品”时，不做确定性行业否定推断。

### 提示词契约测试

- DeepSeek payload 包含涵摄专用上下文；
- policy 明确行业标签不等于法律身份；
- policy 明确未核验补充背景不能单独支持确定违规。

### 确定性保护测试

- 显式冲突下，保健食品专属规则从 `confirmed_violation` 降为 `needs_fact_verification`；
- 通用 `GEN-MED-001` 仍为 `confirmed_violation`；
- 没有冲突时不改写 LLM 判断；
- 不修改 `not_applicable` 判断。

### 回归测试

- 关键词召回继续只使用文案；
- 语义召回继续包含补充背景；
- `/audit` 契约、父规则去重、双 ID 和风险路由测试通过；
- 现有游戏爆率和良好风尚案例不回归。

### 真实模型验证

使用三个已有案例重跑 DeepSeek + 智谱：

1. 游戏爆率：仍为事实核验；
2. 美妆侮辱：良好风尚仍为确定违规；
3. 普通果汁治癌：
   - `GEN-MED-001` 为 `confirmed_violation`；
   - 保健食品专属规则不得仅凭行业标签为 `confirmed_violation`；
   - 修改建议不得把“添加本品不能代替药物”作为普通果汁的核心整改方案。

## 修改文件范围

预计仅修改：

- `rule_engine/src/rule_engine.py`：构建涵摄专用上下文和冲突信号，并在审核流程中使用；
- `rule_engine/src/llm_judgment.py`：增加溯源政策和确定性保护；
- 现有测试文件，必要时新增一个聚焦测试文件。

不修改规则 JSON、向量索引、RAG 服务、飞书状态机或云端环境变量。

## 验收标准

1. 涵摄专用上下文完整包含补充背景及来源标记；
2. 行业字段被明确标记为召回和路由标签；
3. 行业显式冲突不能仅凭 LLM 波动绕过；
4. 通用直接内容违规不被降级；
5. `/audit` 输入输出契约不变；
6. 相关单元测试和全量测试通过；
7. 三个真实案例连续两轮不出现行业标签直接确认产品专属规则的问题。
