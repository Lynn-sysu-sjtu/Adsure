# Ads Penalty RAG Project Instructions

你正在为“广告合规 AI”项目构建行政处罚案例库。

## 目标

构建可用于 RAG 检索的广告行政处罚案例库，优先覆盖：
- 广告法
- 互联网广告管理
- 公法合规
- 行政处罚
- 监管口径
- 市场监管总局及地方市场监管部门公开案例

## 禁止事项

- 不得编造案例、处罚金额、处罚机关、法律依据。
- 不得把律所文章或媒体报道当成处罚事实的主来源。
- 不得绕过 robots.txt 或使用高频请求。
- 不得抓取需要登录、验证码或非公开接口的数据。
- 不得把 API key、cookie、token 写入代码。
- 不得删除 data/raw_html、data/raw_text、data/structured 中的原始数据。

## 数据源优先级

P0：国家市场监督管理总局公开典型案例
P1：地方市场监管局行政处罚公开
P2：信用中国公开处罚信息
P3：律所文章、媒体报道，仅作口径参考，不作处罚事实依据

## 输出要求

每条案例必须输出：
- case_id
- title
- source_name
- source_url
- publish_date
- penalty_authority
- party_name
- industry
- product_or_service
- ad_channel
- risk_dimensions
- illegal_claims
- facts_summary
- legal_basis
- penalty_result
- penalty_amount
- regulatory_logic
- mapped_rule_ids
- keywords
- vector_text
- review_status

## RAG 原则

vector_text 必须是自然语言场景描述，不得写成关键词堆砌。
监管处罚案例只用于规则 RAG，不等同于产品事实核验。
所有结构化结果必须保留 source_url 和 raw_text_path，便于人工回溯。
