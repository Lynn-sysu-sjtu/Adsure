# /audit 真实物料测试案例选择报告

> 本批数据由现有待核验候选案例中的 `illegal_claims` 逐字抽取。原候选案例均未完成 source_url 核验，本文件只用于规则引擎测试，不属于 production RAG。

## 汇总

- 总数：20
- 行业分布：美妆 5 条；保健食品 5 条；游戏 5 条；通用 5 条
- 风险分布：高 13 条；中 5 条；低 1 条；无明显风险 1 条
- 路由分布：运营 2 条；运营补资料 5 条；法务 13 条

## 已选案例

| 测试案例 | 行业 | 风险 | 路由 | 原候选案例 | 广告文案 |
|---|---|---|---|---|---|
| REAL-GAME-001 游戏充值奖励允诺不清 | 游戏 | 高 | 法务 | sector_docx__game__19894e09 | 充三元送一只狗，充六元送神兽白虎，充十元就送召唤月灵 |
| REAL-GAME-002 盲盒概率鉴定背书宣称 | 游戏 | 高 | 法务 | sector_docx__game__d9a46e29 | 商品概率经司法鉴定真实有效，请放心购买 |
| REAL-GAME-003 游戏福利码奖励条件不清 | 游戏 | 中 | 运营补资料 | sector_docx__game__4cff4dd4 | 888888仙玉+经验丹+六阶仙器8 |
| REAL-GAME-004 游戏超高爆率宣传 | 游戏 | 中 | 运营补资料 | sector_docx__game__b5daf3c4 | 超高爆率乐翻天 |
| REAL-GAME-005 游戏专属客服单独宣称 | 游戏 | 低 | 运营 | sector_docx__game__cc400e61 | 专属客服 |
| REAL-COSM-001 美妆产品杀菌消炎医疗用语 | 美妆 | 高 | 法务 | sector_docx__beauty__5560f828 | 杀菌、消炎、镇痛 |
| REAL-COSM-002 美妆服务多项最高级表述 | 美妆 | 高 | 法务 | sector_docx__beauty__6091c23e | 材料最放心、效果最完美、质量最无忧 |
| REAL-COSM-003 面膜渗透力倍数功效宣称 | 美妆 | 中 | 运营补资料 | sector_docx__beauty__80f1858a | 渗透力高达70倍 |
| REAL-COSM-004 普通化妆品美白祛斑宣称 | 美妆 | 高 | 法务 | sector_docx__beauty__ad8eba05 | 美白、祛斑、提亮肤色 |
| REAL-COSM-005 普通化妆品防晒功效宣称 | 美妆 | 中 | 运营补资料 | sector_docx__beauty__b7712cbc | 防晒 |
| REAL-HF-001 普通食品包装宣称预防肿瘤 | 保健食品 | 高 | 法务 | sector_docx__health__47adc1ea | 具有增强免疫力，延缓衰老，预防心脑血管硬化，抑制肿瘤发生和生长等作用 |
| REAL-HF-002 普通食品朋友圈宣称治疗癌症 | 保健食品 | 高 | 法务 | sector_docx__health__d8460228 | 治疗肝癌、肺癌、结肠癌等80%-90%癌症病类 |
| REAL-HF-003 会销普通食品逆转慢性病宣称 | 保健食品 | 高 | 法务 | sector_docx__health__70bd40e0 | 逆转衰老，消除多种老年慢性病 |
| REAL-HF-004 保健食品清除血管斑块宣称 | 保健食品 | 高 | 法务 | sector_docx__health__df7e40d5 | 清除血液垃圾斑块，针对心脑血管疾病及症状作用明显 |
| REAL-HF-005 保健食品批准功能对照样本 | 保健食品 | 无明显风险 | 运营 | sector_docx__health__f92a771c | 补充钙 |
| REAL-GEN-001 服务品牌第一宣称 | 通用 | 高 | 法务 | excel_candidate__absolute_terms__1c28d555 | 阳光车导专车私导第一品牌 |
| REAL-GEN-002 房地产固定回报承诺 | 通用 | 高 | 法务 | excel_candidate__real_estate_misleading__c7de0984 | 在微信公众号发布广告，含有前五年固定回报（分别为6%、6%、7%、8%、9%）等升值承诺内容 |
| REAL-GEN-003 医疗统计数据未标出处 | 通用 | 中 | 运营补资料 | excel_candidate__improper_citation__f79ab438 | 我国每年肝癌发生病例占全球肝癌发生病例的55% |
| REAL-GEN-004 理疗产品抑制癌细胞宣称 | 通用 | 高 | 法务 | excel_candidate__false_misleading_claim__a55ab6a8 | 抑制癌细胞 |
| REAL-GEN-005 食品治疗白血病宣称 | 通用 | 高 | 法务 | excel_candidate__live_commerce_ad__a298aa7b | 对治疗白血病有很好疗效 |

## 使用限制

- `/audit` 请求时只发送 `input_payload`；`human_reference` 仅用于评估，`provenance` 仅用于回溯。
- 不得把本测试集作为已核验行政处罚事实或 production RAG 数据使用。
- “低”和“无明显风险”只表示对当前单条广告物料的预期，不代表对原案例全部行为的判断。
- 完成 source_url 核验前，不应对外引用原处罚机关、金额或裁判结论。
