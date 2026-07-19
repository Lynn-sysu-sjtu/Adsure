# 双规则身份设计修订

日期：2026-07-19  
状态：用户已确认  
修订对象：`2026-07-19-rule-governance-and-subsumption-design.md`

## 1. 修订原因

正式扫描发现规则库共有 892 条规则，存在 127 组重复 `rule_id`，涉及 608 条规则记录。一次性人工重命名会大面积影响向量索引、baseline、历史报告和外部展示，因此原“立即使全部 rule_id 唯一”的方案调整为双 ID。

## 2. 身份字段

```text
rule_uid：全局唯一、稳定、不可复用的内部主键
rule_id：原业务编号，作为兼容字段和人类可读编号保留
```

`rule_uid` 负责：

- 规则加载后的唯一身份；
- 父规则和场景向量归属；
- 三路召回合并；
- 法律问题分组；
- DeepSeek 候选及返回值校验；
- baseline 精确身份指标；
- 向量索引关联。

`rule_id` 继续负责：

- `/audit.matched_rules.rule_id` 向后兼容；
- 飞书和历史报告的人类可读展示；
- 旧测试用例的兼容匹配。

## 3. rule_uid 生成与稳定性

对于缺少 `rule_uid` 的规则，以规范化后的以下字段生成一次性确定性 UID：

```text
source_file
legacy rule_id
title
legal_basis中的source/article/text
```

生成格式：

```text
RU-<SHA256前20位大写十六进制>
```

规则：

- UID 写回规则 JSON 后永久保留；
- 后续标题或法条修改不得重新生成已有 UID；
- 生成器只处理缺少 UID 的规则；
- 相同输入生成相同 UID，重复执行幂等；
- 哈希碰撞或现有 UID 重复时拒绝写入；
- 新增规则必须在进入正式规则库前生成 UID。

## 4. 校验策略

严格部署校验要求：

```text
empty_rule_uid_count = 0
duplicate_rule_uid_count = 0
orphan_vector_rule_uid_count = 0
orphan_group_rule_uid_count = 0
```

重复 `rule_id` 继续生成治理报告，但在双 ID 迁移阶段不阻止规则库加载。规则标题、来源和 UID 必须随重复 ID 一并记录，方便后续逐批规范业务编号。

## 5. 运行时兼容

内部合并键统一改为：

```python
rule.get("rule_uid") or rule.get("rule_id")
```

兼容兜底只允许在迁移测试阶段使用；正式部署校验通过后，每条规则都必须具有 `rule_uid`。

`matched_rules` 保留现有 `rule_id`，新增可选字段：

```json
{
  "rule_uid": "RU-0123456789ABCDEF0123",
  "rule_id": "COSM-002"
}
```

飞书端不需要修改。

## 6. LLM 涵摄契约

传给 DeepSeek 的候选规则同时包含 `rule_uid` 和 `rule_id`。模型必须返回 `rule_uid`；程序以 `rule_uid` 校验候选身份。`rule_id` 只用于说明和展示，不能作为唯一校验键。

## 7. 向量和分组资产

- 向量索引每个父规则和场景条目必须包含 `rule_uid`；
- 旧 `rule_id` 继续保留用于调试展示；
- 法律问题分组使用 `member_rule_uids`；
- `supporting_rule_uids` 作为内部折叠结果；
- baseline 新增 `expected_rule_uids`，旧 `expected_rule_ids` 保持兼容。

## 8. 分阶段治理

第一阶段完成全部 `rule_uid` 生成和内部身份切换，立即解决错误合并和身份错配。第二阶段根据法律问题分组和真实审核使用频率，逐批规范重复的业务 `rule_id`，不阻塞本次涵摄工程。

