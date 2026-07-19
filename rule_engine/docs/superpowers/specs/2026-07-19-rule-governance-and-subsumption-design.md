# 规则治理与结构化涵摄完整工程 TDD 设计

日期：2026-07-19  
状态：已获用户口头确认，待书面文档复核  
范围：`Adsure/rule_engine`

## 1. 目标与原则

本工程把规则引擎从“召回候选直接展示”改造成“宽召回、严涵摄、确认后展示”，并同时治理规则 ID 冲突和近义规则膨胀。

```text
规则库加载
→ Rule ID 唯一性校验
→ 关键词/正则、智谱场景向量、开放规则目录并行召回
→ 父规则去重
→ 法律问题分组去重
→ 最高效力主规则＋当前平台规则选择
→ 最多8条候选进入DeepSeek
→ DeepSeek结构化事实涵摄
→ confirmed_violation / needs_fact_verification / not_applicable
→ 程序校验和过滤
→ 风险、路由、审核意见合成
→ 保持原/audit契约输出
```

原则：

- 召回可以宽，涵摄必须严。
- 候选规则不得直接作为最终命中规则展示。
- `needs_fact_verification` 必须保留，但不得被表述为已确认违法。
- 直接内容违规不得被补资料事项遮蔽。
- LLM 异常时不展示未经确认的候选规则，统一转法务人工复核。
- 飞书状态机、飞书字段和 `/audit` 顶层输入输出保持不变。
- 复用当前最终 DeepSeek 涵摄调用，不增加新的在线 LLM 调用。

## 2. 范围与数据语义

本工程包含：

1. Rule ID 冲突扫描和迁移；
2. 法律问题分组及近义规则折叠；
3. 三路召回后的候选池治理；
4. DeepSeek 结构化涵摄；
5. 最终规则、风险、路由和意见合成；
6. baseline、接口兼容、飞书烟测和云端部署验证。

不修改飞书请求字段、多维表格字段、`/audit` URL、顶层 `code/msg/data`、既有风险和路由枚举，以及飞书状态机业务逻辑。

内部明确区分：

```text
candidate_rules：召回和候选治理后的内部候选，不回传飞书
rule_judgments：DeepSeek对每条候选规则的结构化涵摄结果
matched_rules：经程序校验后确认违规或确需事实核验的最终规则
```

`matched_rules` 只保留 `confirmed_violation` 和 `needs_fact_verification`。`not_applicable` 仅用于内部诊断，不参与风险、路由、违规类型和法律依据展示。

## 3. Rule ID 冲突治理

### 3.1 校验器

新增 `src/rule_asset_validator.py`，检查：

- `rule_id` 非空且全库唯一；
- 同一 ID 不得对应不同标题、法条或规则内容；
- 父规则内 `scenario_id` 唯一；
- 向量索引、baseline 和法律问题分组中的 rule ID 均有效。

### 3.2 迁移

迁移表保存为 `migrations/rule_id_migrations.json`，必须结合来源文件和旧 ID 定位，避免同一旧 ID 对应多条规则时误改：

```json
{
  "source_file": "美妆/某规则文件.json",
  "old_rule_id": "DY-COSM-002",
  "new_rule_id": "DY-COSM-SPECIAL-EFFICACY-002",
  "reason": "解决跨文件ID冲突"
}
```

迁移同步更新规则 JSON、向量索引、baseline 用例、法律问题分组和正式代码/测试中的 ID 引用。迁移脚本必须幂等，并在写入前生成冲突报告与变更预览。

验收：

```text
duplicate_rule_id_count = 0
orphan_vector_rule_id_count = 0
orphan_test_expected_rule_id_count = 0
```

## 4. 法律问题分组与近义规则折叠

### 4.1 离线分组

新增 `assets/legal_issue_groups.json`。该文件不得放入 `jsonbase`，避免被现有规则加载器当作规则文档递归加载。

智谱向量离线产生近义规则候选，再根据行业、规范对象、违规行为、法律后果、平台和 trigger layer 等元数据过滤。向量只负责发现近义候选，不单独决定法律等价性；不同 trigger layer 的规则原则上不得折叠。

```json
{
  "issue_group_id": "cosmetic_special_efficacy_filing",
  "title": "化妆品特殊功效与注册备案一致性",
  "member_rule_ids": [
    "COSM-002",
    "DY-COSM-SPECIAL-EFFICACY-002",
    "TB-COSM-SPECIAL-EFFICACY-002",
    "XHS-COSM-SPECIAL-EFFICACY-002"
  ],
  "selection_policy": {
    "primary_rule_strategy": "highest_legal_authority",
    "platform_rule_strategy": "current_platform_only",
    "max_primary_rules": 1,
    "max_platform_rules": 1
  }
}
```

### 4.2 运行时选取

- 已填写平台：保留最高效力法律/规章主规则和一条当前平台实施规则。
- 未填写平台：只保留最高效力主规则，平台规则不进入涵摄池。
- 只有平台规则：仅在平台匹配时保留。
- 同层级依次比较适用范围精确度、构成要件完整度、生效状态、规则具体程度和稳定 ID。

被折叠规则记录为内部 `supporting_rule_ids`，不单独进入 DeepSeek，不在飞书重复展示。

## 5. 候选池治理

召回继续并行执行关键词/正则、智谱场景向量和 DeepSeek 开放性规则目录。

```text
三路结果
→ 相同父rule_id合并
→ 合并召回渠道和证据
→ 法律问题组折叠
→ 平台适用过滤
→ 稳定排序
→ 最多8条进入最终涵摄
```

排序优先级：多路共同命中、开放规则目录、高精度正则、高优先级关键词、当前平台规则、primary 场景向量、fallback 场景向量、普通关键词。

候选池约束：

- 总数最多 8 条；
- 开放性内容规则至少保留 1 个席位；
- fact 规则最多 3 条；
- 同一法律问题组最多 2 条；
- 平台规则最多 2 条。

baseline 分别记录 `candidate_recall` 和 `confirmed_match`，不再用最终展示规则代替召回指标。

## 6. DeepSeek 结构化涵摄

每条候选规则输入包括规则 ID、标题、效力层级、法律依据、规则正文、适用范围、trigger layer、检测标准、召回原因、命中文案证据，以及行业、平台、产品和备案上下文。

输出契约：

```json
{
  "rule_id": "string",
  "applicability_status": "confirmed_violation | needs_fact_verification | not_applicable",
  "material_evidence": "文案连续原文",
  "satisfied_elements": ["已满足要件"],
  "unsatisfied_elements": ["未满足要件"],
  "missing_facts": ["完成判断所需事实"],
  "applicability_reason": "结合规则与上下文的理由",
  "confidence": 0.0
}
```

状态标准：

- `confirmed_violation`：文案证据直接、关键要件已满足、不依赖未提供的外部事实。
- `needs_fact_verification`：触及规范对象，但结论依赖备案、资质、证明或履约事实，并明确列出 `missing_facts`。
- `not_applicable`：仅命中宽泛词、必要对象或前提缺失、上下文不符、无原文证据或属于语义噪声。

程序校验：

- ID 必须来自本次候选池；
- 状态必须属于固定枚举；
- DeepSeek 必须对每条候选规则恰好返回一次判断；
- 漏返回、重复返回或返回数量不一致均视为涵摄失败，不得静默当作不适用；
- confirmed 必须引用文案连续原文；
- needs fact 必须具有非空 `missing_facts`；
- LLM 不得新增规则；
- 第一版记录 confidence，但不做硬阈值过滤。

## 7. 最终结果、风险和路由

### 7.1 接口兼容

`matched_rules` 保留原有必需字段：

```text
rule_id, title, dimension, risk_level, judgment, match_reason
```

增加可选字段：

```text
applicability_status, material_evidence, satisfied_elements,
unsatisfied_elements, missing_facts, applicability_reason, confidence
```

现有响应 schema 允许 `matched_rules` 项目包含扩展字段，飞书端也不直接解析该数组，因此属于向后兼容扩展。

### 7.2 主意见、风险与路由

- 存在 confirmed：主意见为“违规修改”；补资料只能作为附带事项。
- 只有 needs fact：主意见为“需补资料”。
- 全部不适用：主意见为“无明显风险”。

风险只使用涵摄确认后的规则和 LLM 个案风险：confirmed 高则最终高，confirmed 中则至少中，只有 needs fact 默认中，全部不适用为无明显风险，涵摄异常为中风险人工复核。原始候选不得触发风险兜底。

路由只使用最终适用规则：confirmed 法务规则转法务；普通补资料转运营；需要法务的 fact 规则转法务；全部不适用转运营；涵摄异常转法务。

审核意见排序：

```text
意见类型
核心确认风险
附带事实核验
确认适用规则
需事实核验规则
法律依据
修改建议
```

`not_applicable` 规则及其法条不得展示。

## 8. 保守异常降级

触发条件：DeepSeek 超时、网络异常、非 JSON、关键结构缺失、候选漏返回或重复返回、所有 ID 均在候选池外、结构化校验失败或内部异常。

统一输出：

```text
code=0
msg=ok
风险=中
routing=法务
matched_rules=[]
意见类型=人工复核
```

审核意见说明涵摄未完成，不展示未经确认的候选规则。日志记录请求 ID、异常类型、模型耗时、候选 ID 和解析失败原因，不记录 API Key 或敏感请求头。

## 9. TDD 测试设计

### 9.1 资产与迁移

新增 `test_rule_asset_validator.py`、`test_rule_id_migration.py`，覆盖重复 ID、不同标题/法条冲突、迁移精确定位、幂等、向量/baseline/分组引用同步、孤儿引用和迁移后二次校验。

### 9.2 法律问题分组

新增 `test_legal_issue_group_assets.py`、`test_legal_issue_rule_selection.py`、`test_semantic_rule_clustering.py`，覆盖成员有效性、trigger layer 隔离、效力层级选主规则、当前平台保留、其他平台过滤、无平台过滤、supporting rules、错误近义合并和结果稳定性。

### 9.3 候选池

新增或扩展 `test_candidate_pool_governance.py`、`test_recall_merge_and_judgment_pool.py`，覆盖三路父规则去重、渠道证据合并、问题组折叠、席位限制、最多 8 条、平台优先、开放规则保留、稳定排序和单路异常降级。

### 9.4 涵摄契约

新增 `test_subsumption_contract.py`、`test_subsumption_filter.py`、`test_rule_subsumption_cases.py`，覆盖三种状态、候选外 ID、伪造或非连续证据、needs fact 缺少材料、重复/遗漏规则、非法状态、字段类型错误、中文标点和富文本归一化。

### 9.5 风险、意见与路由

新增 `test_confirmed_rule_risk_synthesis.py`、`test_audit_opinion_priority.py`、`test_confirmed_rule_routing.py`，覆盖违规＋补资料、仅补资料、全部不适用、原始高风险候选最终不适用、高中风险合成、运营/法务路由、核心风险排序、supporting rules 不重复展示和违规类型来源。

### 9.6 异常降级

新增 `test_subsumption_failure_fallback.py`，覆盖超时、网络异常、非 JSON、空结果、非法结构、目录外 ID 和证据校验失败，并断言 `/audit` 返回 `code=0`、中风险、法务、空 matched rules 和人工复核意见。

### 9.7 契约与端到端案例

扩展现有 `/audit` 契约测试，确保全部原字段存在、`matched_rules` 仍为数组、新字段可选且飞书无需修改。

核心案例：

1. “美白精华一降价，你还不是像狗一样跑过来”：良好风俗 confirmed，美白备案 needs fact，虚假宣传/未成年人/数据引证不适用；高风险、法务、违规修改。
2. “我们的美白精华正在促销”：仅美白备案 needs fact；中风险、运营、需补资料。
3. “一次使用立刻变白三个色号”：效果夸大或虚假宣传 confirmed。
4. “儿童频道推荐这款美白精华”：未成年人媒介规则 confirmed，同时保留美白备案核验。
5. “实验数据显示，使用7天美白率提升93%”：数据引证规则适用并需证明材料。
6. 所有候选不适用：空 matched rules、无明显风险、运营。
7. 模型异常：空 matched rules、中风险、法务、人工复核。

## 10. Baseline 与验收指标

拆分指标：

```text
candidate_recall
confirmed_recall
confirmed_precision
fact_verification_accuracy
not_applicable_filter_accuracy
```

同时统计平均候选数、平均最终规则数、压缩率、无关规则过滤率、核心风险识别率、异常率、平均耗时、P50、P95 和契约通过率。

目标：

```text
Rule ID冲突 = 0
/audit契约 = 100%
目标规则候选召回不低于当前baseline
无关规则过滤率 ≥ 80%
核心目标案例主风险排序 = 100%
平均涵摄池 ≤ 8
平均最终展示规则建议 ≤ 4
```

## 11. 实施批次与工程量

实施批次：

1. 资产安全底座：ID 扫描、报告、迁移和引用一致性；
2. 法律问题分组：分组资产、效力层级和平台选择；
3. 候选池治理：父规则去重、问题组折叠、席位和排序；
4. 结构化涵摄：输出契约、三状态解析和确定性校验；
5. 风险与意见合成：matched rules、风险、routing、意见和异常降级；
6. 集成验证：全量测试、mock baseline、真实 DeepSeek＋智谱 baseline、飞书烟测和云端发布。

每个批次严格执行红—绿—重构，不允许先改实现再补测试。

预计：新增核心模块 4～6 个，修改核心模块 4～6 个，新增或扩展测试文件 10～14 个，新增测试约 60～90 项，完整测试约 170～200 项；完成 ID 迁移后重建一次智谱向量索引，并至少运行两轮真实 baseline。

## 12. 最终验收

部署前必须同时满足：

- 全库 Rule ID 唯一；
- 向量索引和测试资产无孤儿引用；
- 法律问题组成员有效；
- 目标候选召回不下降；
- 近义规则不再占满涵摄池；
- `not_applicable` 不进入 `matched_rules`；
- `needs_fact_verification` 正确保留；
- 直接违规优先于补资料；
- DeepSeek 异常统一转法务；
- `/audit` 输入输出契约不变；
- 飞书状态机无需修改；
- 全部单元测试、真实 baseline 和云端目标案例验证通过。

