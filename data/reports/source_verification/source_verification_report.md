# 候选案例核源核查结果（115 条）
> 生成时间：2026-09-15 03:04（Asia/Shanghai）
## 一句话结论
**115 条候选全部判定 `needs_human`，无一可转生产（`source_verified=false`）。** 原因不是“没查”，而是：① 115 条全部是法院案号（90 条行政 + 25 条民事），**没有一条是处罚决定书号（市监处…）**；② 法院案号指定来源「裁判文书网」需实名登录、「信用中国」需登录，当前无合法会话（硬红线 2）；③ 已按 ≥2.5 秒/条对 115 条做公开检索，**零命中官方处罚决定页**。
## 0. 核查对象分流
- 63 条有案号清单（checklist）：全部为**法院案号**，无处罚决定书号。
- 52 条无检索词清单：回原始 Excel（`40个十大类违法广告行政处罚案例汇总表.xlsx`）确认，**原表第 4 列「案号」其实都有案号**（如 `（2018）苏0508行初268号`），JSON 的 `case_number` 字段也存在，只是 `source_lookup_query` 为空；已全部重建检索式 = 完整案号 + 当事人名/案名。
- 案号类型：行政类（行审/行初/行终）90 条、民事类（民初/民终）25 条；处罚决定书号 0 条。
## 1. 执行过程（对照 SOP 四步）
### 第一步 · 案号类型分流
- 全部 115 条为法院案号 → 按 SOP 应去裁判文书网。裁判文书只能证明「有这起诉讼/执行」，不能当作处罚决定书。
### 第二步 · 检索
- 入口可达性：`wenshu.court.gov.cn` 首页可达但检索需实名登录；`creditchina.gov.cn` 返回 412 反爬且需登录；地方市监局/搜索引擎对「法院案号」无索引。
- 公开检索：对 115 条逐一执行「完整案号 + 当事人」精确检索（搜狗为主，必应/360 抽样复核），请求间隔 ≥2.5 秒；前 37 条搜狗返回的是站点模板/无关内容（0 条官方命中），之后被反爬 403 拦截。**全程 0 条 gov.cn/court/creditchina 官方命中。**
### 第三步 · 逐字段比对
- 未取得任何官方原文，8 项比对无法执行（无从核起），`matched=[]`、`mismatched=[]`。
### 第四步 · 判定
- 全部 115 条：`needs_human`（需登录/验证码且无合法会话）。
## 2. 三条硬红线合规情况
1. ✅ 未绕 robots.txt；请求间隔 ≥2.5 秒/条，总请求量 115 条级别，未高频。
2. ✅ 未破验证码、未抓登录/非公开接口；未使用任何绕过手段；无合法登录会话，故交人工。
3. ✅ 未把媒体当已核源：检索到的公众号/媒体结果仅记为线索，未用于任何 `verified` 判定。
## 3. 人工后续动作（要让某条转 production 必需）
1. 用**已登录的合法会话**进裁判文书网，按「完整案号 + 当事人」核到裁判文书 → 该条最多可判 `court_only`（证明案件存在，仍不是处罚决定书）。
2. 从裁判文书或地方市监局公示中取得**处罚决定书号（市监处…号）**，再到地方市监局/信用中国核处罚决定原文，8 项一致才可 `verified`。
3. 民事案件（25 条，如毛冉冉系列、游戏充值纠纷）本质是司法参考，**没有行政处罚决定书**，不建议作为行政处罚事实源进入生产 RAG。
## 4. 结果文件
- 机器可读（用户约定格式，115 行 JSONL）：`data/reports/source_verification/source_verification_results.jsonl`
- 同上 JSON 数组：`data/reports/source_verification/source_verification_results.json`
- 每条明细（案号类型/检索式/检索结果数/预期人工结论等）：`data/reports/source_verification/verification_details.jsonl`
- 装配清单（115 条，含重建检索式）：`data/reports/source_verification/assembled_manifest.json`
- 输入文件副本：`data/reports/source_verification/inputs/`
- 检索原始证据（115 条搜索结果）：`/private/tmp/ads_verification_cache/search_pass_results.jsonl`
## 5. 结论分布
| conclusion | 数量 | source_verified |
|---|---|---|
| needs_human | 115 | false |
| verified | 0 | - |
## 6. 逐条明细（115 条）
| case_id | 类型 | 案号 | 案名（截断） | 结论 |
|---|---|---|---|---|
| sector_docx__beauty__0993a40d | 行政 | （2019）浙0105行审2号 | 杭州滨研生物科技有限公司非诉执行案 | needs_human |
| sector_docx__beauty__0beb3b53 | 行政 | （2024）沪7101行初94号 | 上海美狄莎思美奇商贸有限公司诉上海市长宁区市场监督管理局案 | needs_human |
| sector_docx__beauty__1696a02c | 民事 | （2018）鄂0105民初1791号 | 毛冉冉诉广州舒美生物科技有限公司产品责任纠纷案 | needs_human |
| sector_docx__beauty__21f65a16 | 民事 | （2018）鄂0105民初5389号 | 毛冉冉诉深圳市龙岗区亿发日贸易商行网络购物合同纠纷案 | needs_human |
| sector_docx__beauty__2626bbb1 | 行政 | （2022）豫01行终792号 | 郑州市中原区市场监督管理局处罚常某建案 | needs_human |
| sector_docx__beauty__27760156 | 行政 | （2023）川0504行审1号 | 泸州市龙马潭区市场监督管理局申请执行泸州韩美整形美容有限公司 | needs_human |
| sector_docx__beauty__5560f828 | 行政 | （2024）浙0603行审7号 | 绍兴市柯桥区市场监督管理局申请执行绍兴金乌玉农业科技有限公司 | needs_human |
| sector_docx__beauty__6091c23e | 行政 | （2020）鲁0203行初204号 | 青岛天地和装饰设计有限公司诉青岛市市北区市场监督管理局行政处 | needs_human |
| sector_docx__beauty__801cf8d6 | 行政 | （2025）渝0112行审1486号 | 重庆市市场监督管理局申请执行重庆某生物科技有限公司行政处罚案 | needs_human |
| sector_docx__beauty__80f1858a | 行政 | （2018）苏0508行初268号 | 苏州开禧医药有限公司诉苏州市吴江区市场监督管理局行政处罚案 | needs_human |
| sector_docx__beauty__96b1a837 | 民事 | （2018）鄂0105民初1792号 | 毛冉冉诉广州娇比萃化妆品有限公司产品责任纠纷案 | needs_human |
| sector_docx__beauty__9b9bec19 | 行政 | （2018）鲁0611行审37号 | 烟台市福山区市场监督管理局申请执行仙品果蔬专业合作社行政处罚 | needs_human |
| sector_docx__beauty__a28e6eb6 | 民事 | （2018）鄂0105民初5110号 | 毛冉冉诉广州雅新生物科技有限公司网络购物合同纠纷案 | needs_human |
| sector_docx__beauty__ac711b6d | 行政 | （2019）鲁1424行审75号 | 临邑县临南镇双丰至尚洗化百货商店非诉执行案 | needs_human |
| sector_docx__beauty__ad8eba05 | 民事 | （2021）闽0304民初1796号 | 陈剑力诉河南维颜化妆品有限公司网络购物合同纠纷案 | needs_human |
| sector_docx__beauty__adcff395 | 行政 | （2021）豫01行终177号 | 郑州市中原区市场监督管理局诉河南聚美化妆品公司行政处罚案 | needs_human |
| sector_docx__beauty__b2d8108c | 行政 | （2020）鄂1223行审52号 | 崇阳县市场监督管理局申请执行御升广盈生物科技（深圳）有限公司 | needs_human |
| sector_docx__beauty__b7712cbc | 民事 | （2016）粤0111民初9365号 | 林福平诉建德市艾氏贸易有限公司网络购物合同纠纷案 | needs_human |
| sector_docx__beauty__ba07e527 | 行政 | （2018）浙0703行审23号 | 金华市金东区市场监督管理局申请执行俞俊玲行政处罚案 | needs_human |
| sector_docx__beauty__cfc7d2a0 | 行政 | （2019）桂0681行初4号 | 韦彩群诉东兴市市场监督管理局行政案 | needs_human |
| sector_docx__beauty__ec0e2c05 | 行政 | （2025）苏0282行审5号 | 宜兴市市场监督管理局申请执行孙某行政处罚案 | needs_human |
| sector_docx__beauty__f46b8aed | 民事 | （2020）鄂0115民初732号 | 毛冉冉诉广州医美医药科技有限公司网络购物合同纠纷案 | needs_human |
| sector_docx__beauty__f500e86e | 行政 | （2016）豫04行终126号 | 驻马店市晨钟生物科技有限公司诉平顶山市工商行政管理局新华分局 | needs_human |
| sector_docx__game__19894e09 | 民事 | （2023）粤0192民初1448号 | 王越诉广州鑫晨网络科技有限公司等网络服务合同纠纷案 | needs_human |
| sector_docx__game__3ba48058 | 民事 | （2020）粤0192民初4007号 | 陈睿泽诉广州库洛科技有限公司网络服务合同纠纷案 | needs_human |
| sector_docx__game__4cff4dd4 | 民事 | （2025）粤0192民初9279号 | 许某诉广州某公司等网络服务合同纠纷案 | needs_human |
| sector_docx__game__53e9096b | 民事 | （2025）沪0104民初7362号 | 郭某诉某某公司等服务合同纠纷案 | needs_human |
| sector_docx__game__54a80f6c | 民事 | （2025）京0491民初7134号 | 刘某诉某科技公司网络服务合同纠纷案 | needs_human |
| sector_docx__game__551a4343 | 民事 | （2023）赣1104民初2952号 | 朱某伟诉江西某某信息技术有限公司网络服务合同纠纷案 | needs_human |
| sector_docx__game__6a91b70a | 民事 | （2021）粤0192民初25167号 | 鲍道成诉广州掌跃网络科技有限公司等网络服务合同纠纷案 | needs_human |
| sector_docx__game__6b073bbb | 民事 | （2024）浙0192民初1779号 | 吴某、郝某诉杭州某公司网络服务合同纠纷案 | needs_human |
| sector_docx__game__a5b354d7 | 民事 | （2020）粤0192民初22669号 | 赵剑磊诉三七互娱（上海）科技有限公司等网络服务合同纠纷案 | needs_human |
| sector_docx__game__b5daf3c4 | 民事 | （2025）京0491民初25297号 | 孙某诉某（北京）科技有限公司网络服务合同纠纷案 | needs_human |
| sector_docx__game__cc400e61 | 民事 | （2023）京0491民初1062号 | 王某诉北京某公司网络服务合同纠纷案 | needs_human |
| sector_docx__game__ccf5c3bb | 民事 | （2023）琼96民终6628号 | 朱某伟诉海南某公司合同纠纷案 | needs_human |
| sector_docx__game__d9a46e29 | 行政 | （2024）川14行终29号 | 四川某某科技有限公司诉眉山市市场监督管理局行政处罚案 | needs_human |
| sector_docx__game__e9a15585 | 民事 | （2025）粤0192民初19683号 | 闻某诉广州某公司网络服务合同纠纷案 | needs_human |
| sector_docx__health__1a078812 | 行政 | （2019）川2021行审14号 | 安岳县市场监督管理局申请执行康寿源健康生活馆行政处罚案 | needs_human |
| sector_docx__health__21364f49 | 行政 | （2016）浙07行终370号 | 义乌市爽爽戒烟咨询服务站诉义乌市市场监督管理局行政处罚案 | needs_human |
| sector_docx__health__32abaf01 | 行政 | （2020）苏0412行审155号 | 常州市武进区市场监督管理局申请执行颐圣堂食品店行政处罚案 | needs_human |
| sector_docx__health__47adc1ea | 行政 | （2024）川0105行审11号 | 成都市青羊区市场监督管理局申请执行成都某有限公司行政处罚案 | needs_human |
| sector_docx__health__4868d2df | 行政 | （2019）闽0824行初28号 | 连城县文亨良瑞食品经营部诉连城县市场监督管理局案 | needs_human |
| sector_docx__health__48c50f1c | 行政 | （2020）云2301行初88号 | 楚雄四世同堂食品经营部诉楚雄市市场监督管理局行政处罚案 | needs_human |
| sector_docx__health__4d2b48f7 | 行政 | （2020）浙1102行初42号 | 丽水市莲都区运祥日用品商行诉丽水市市场监督管理局案 | needs_human |
| sector_docx__health__5560f828 | 行政 | （2024）浙0603行审7号 | 绍兴市柯桥区市场监督管理局申请执行绍兴金乌玉农业科技有限公司 | needs_human |
| sector_docx__health__5a23d058 | 行政 | （2020）鲁0811行审94号 | 济宁市任城区市场监督管理局申请执行婧港商贸公司行政处罚案 | needs_human |
| sector_docx__health__5d46a744 | 行政 | （2020）粤06行终286号 | 佛山市南海区益尔康保健品商行诉佛山市南海区市场监督管理局行政 | needs_human |
| sector_docx__health__6a1dde83 | 行政 | （2021）冀0903行审4号 | 沧州市运河区市场监督管理局申请执行东方红保健食品经销处行政处 | needs_human |
| sector_docx__health__70bd40e0 | 行政 | （2020）鲁0322行审7号 | 高青县市场监督管理局申请执行华康保健品经营部行政处罚案 | needs_human |
| sector_docx__health__801cf8d6 | 行政 | （2025）渝0112行审1486号 | 重庆市市场监督管理局申请执行重庆某生物科技有限公司行政处罚案 | needs_human |
| sector_docx__health__87d3834c | 行政 | （2025）苏0282行审17号 | 宜兴市市场监督管理局申请执行宜兴市某某服务部行政处罚案 | needs_human |
| sector_docx__health__9e72583c | 行政 | （2019）浙1122行审36号 | 缙云县市场监督管理局申请执行王志虎行政处罚案 | needs_human |
| sector_docx__health__aba1a4e2 | 行政 | （2020）川0502行审15号 | 泸州市澳鼎医疗器械有限公司非诉执行案 | needs_human |
| sector_docx__health__abf17acb | 民事 | （2025）川0114民初296号 | 何某诉太原某公司买卖合同纠纷案 | needs_human |
| sector_docx__health__aeccb98a | 行政 | （2020）浙0105行审18号 | 杭州市拱墅区海研保健食品经营部非诉执行案 | needs_human |
| sector_docx__health__b99ce8d0 | 行政 | （2020）鲁0102行审30号 | 济南历下金泰保健食品经营部非诉执行案 | needs_human |
| sector_docx__health__bd569381 | 行政 | （2020）浙1102行初41号 | 丽水市莲都区善博广告设计工作室诉丽水市市场监督管理局案 | needs_human |
| sector_docx__health__bdad9230 | 行政 | （2021）豫1024行审31号 | 鄢陵县市场监督管理局申请执行婴智杰母婴商城行政处罚案 | needs_human |
| sector_docx__health__ce7b9365 | 行政 | （2025）皖0722行审19号 | 枞阳县市场监督管理局申请执行社区生活馆行政处罚案 | needs_human |
| sector_docx__health__d8460228 | 行政 | （2025）桂13行终37号 | 张某甲诉象州县某局行政处罚案 | needs_human |
| sector_docx__health__d9cb5caf | 行政 | （2020）鲁0725行审15号 | 昌乐县市场监督管理局申请执行吴素杰行政处罚案 | needs_human |
| sector_docx__health__df7e40d5 | 行政 | （2019）浙0211行审74号 | 宁波市镇海区市场监督管理局申请执行瑞寿食品商行行政处罚案 | needs_human |
| sector_docx__health__f92a771c | 行政 | （2020）桂0107行初80号 | 南宁武鸣活力保健食品有限公司诉南宁市武鸣区市场监督管理局行政 | needs_human |
| excel_candidate__absolute_terms__0963e2cd | 行政 | （2019）浙03行终113号 | 温州经济技术开发区海城乔诗丹顿卫浴洁具店与温州市市场监督管理 | needs_human |
| excel_candidate__absolute_terms__1c28d555 | 行政 | （2017）京0108行初511号 | 北京假日阳光环球旅行社有限公司与北京市工商行政管理局海淀分局 | needs_human |
| excel_candidate__absolute_terms__434f2186 | 行政 | （2016）豫0104行初138号 | 郑州尚之泉文化传播有限公司与郑州市工商行政管理局金水分局行政 | needs_human |
| excel_candidate__absolute_terms__92b4e4d1 | 行政 | （2018）豫01行终314号 | 郑州市金水区工商管理和质量技术监督局与郑州市科视视光技术有限 | needs_human |
| excel_candidate__absolute_terms__f8beaa91 | 行政 | （2019）浙03行终112号 | 温州经济技术开发区海城叶挺亮洁具配件厂与温州市市场监督管理局 | needs_human |
| excel_candidate__cosmetic_medical_claim__2280310e | 民事 | （2017）陕01民再74号 | 温拓与天津百恩汇生物科技有限公司买卖合同纠纷再审案 | needs_human |
| excel_candidate__cosmetic_medical_claim__80f1858a | 行政 | （2018）苏0508行初268号 | 苏州开禧医药有限公司与苏州市吴江区市场监督管理局行政处罚案 | needs_human |
| excel_candidate__cosmetic_medical_claim__865b8bc7 | 民事 | （2015）朝民（商）初字第49845号 | 周致正与北京创锐文化传媒有限公司买卖合同纠纷案 | needs_human |
| excel_candidate__cosmetic_medical_claim__ac711b6d | 行政 | （2019）鲁1424行审75号 | 临邑县市场监督管理局、临邑县临南镇双丰至尚洗化百货商店非诉执 | needs_human |
| excel_candidate__cosmetic_medical_claim__b2d8108c | 行政 | （2020）鄂1223行审52号 | 崇阳县市场监督管理局、御升广盈生物科技（深圳）有限公司非诉执 | needs_human |
| excel_candidate__cosmetic_medical_claim__ec0e2c05 | 行政 | （2025）苏0282行审5号 | 宜兴市市场监督管理局、孙某非诉行政行为申请执行审查案 | needs_human |
| excel_candidate__false_misleading_claim__700fe82c | 行政 | （2020）浙0111行审149号 | 杭州市富阳区市场监督管理局、东莞市米乐真科技有限公司非诉执行 | needs_human |
| excel_candidate__false_misleading_claim__801cf8d6 | 行政 | （2025）渝0112行审1486号 | 重庆市市场监督管理局与重庆某生物科技有限公司行政非诉审查案 | needs_human |
| excel_candidate__false_misleading_claim__a55ab6a8 | 行政 | （2024）苏0282行审64号 | 宜兴市市场监督管理局、宜兴市某某服务部行政处罚非诉执行审查案 | needs_human |
| excel_candidate__false_misleading_claim__a9cfdd3e | 行政 | （2014）南召行审字第00050号 | 南召县工商行政管理局申请执行闫学军行政处罚案 | needs_human |
| excel_candidate__false_misleading_claim__f5a6d6c9 | 行政 | （2020）辽0105行初86号 | 沈阳美希公司与沈阳市沈河区市场监督管理局行政案 | needs_human |
| excel_candidate__food_medical_claim__83ff48dc | 行政 | （2021）浙0521行审9号 | 德清县市场监督管理局、湖州洁净康电子科技有限公司非诉执行审查 | needs_human |
| excel_candidate__food_medical_claim__883f17e8 | 行政 | （2018）黑0603行审1号 | 大庆市食品药品监督管理局、黑龙江易联百货电子商务有限公司非诉 | needs_human |
| excel_candidate__food_medical_claim__b0e7e8a2 | 民事 | （2016）浙0483民初6906号 | 李宗胜与江苏一号农场科技股份有限公司产品责任纠纷案 | needs_human |
| excel_candidate__food_medical_claim__c13d1c27 | 行政 | （2021）云0623行审4号 | 盐津县市场监督管理局、盐津黑凤凰农业有限公司非诉执行审查案 | needs_human |
| excel_candidate__food_medical_claim__fd2c4c40 | 民事 | （2016）京0111民初14505号 | 孙玉民与京之源（北京）农业有限公司北潞园分公司等买卖合同纠纷 | needs_human |
| excel_candidate__health_food_overclaim__32abaf01 | 行政 | （2020）苏0412行审155号 | 常州市武进区市场监督管理局与武进区湖塘颐圣堂食品店、马世开行 | needs_human |
| excel_candidate__health_food_overclaim__87d3834c | 行政 | （2025）苏0282行审17号 | 宜兴市市场监督管理局、宜兴市某某服务部行政处罚非诉执行审查案 | needs_human |
| excel_candidate__health_food_overclaim__d9cb5caf | 行政 | （2020）鲁0725行审15号 | 昌乐县市场监督管理局、吴素杰非诉执行审查案 | needs_human |
| excel_candidate__health_food_overclaim__df7e40d5 | 行政 | （2019）浙0211行审74号 | 宁波市镇海区市场监督管理局、宁波市镇海区招宝山瑞寿食品商行非 | needs_human |
| excel_candidate__health_food_overclaim__f92a771c | 行政 | （2020）桂0107行初80号 | 南宁武鸣活力保健食品有限公司与南宁市武鸣区市场监督管理局行政 | needs_human |
| excel_candidate__improper_citation__63ed8b56 | 行政 | （2020）琼0105行审51号 | 海口市市场监督管理局龙华分局与杨思宝行政处罚非诉执行审查案 | needs_human |
| excel_candidate__improper_citation__7b5e29e0 | 行政 | （2019）鄂1281行初20号 | 广州市哈雷日用品有限公司与赤壁市市场监督管理局行政案 | needs_human |
| excel_candidate__improper_citation__a989a836 | 行政 | （2019）鄂0902行初18号 | 联合利华（中国）有限公司与云梦县市场监督管理局行政案 | needs_human |
| excel_candidate__improper_citation__ea28d99e | 行政 | （2018）鄂1223行初3号 | 广东雪洁日化用品有限公司与崇阳县工商行政管理局行政案 | needs_human |
| excel_candidate__improper_citation__f79ab438 | 行政 | （2024）甘0103行初58号 | 甘肃某某医疗科技有限公司与兰州市城关区市场监督管理局行政案 | needs_human |
| excel_candidate__live_commerce_ad__585696ea | 行政 | （2020）川0113行审13号 | 成都市青白江区市场监督管理局与成都麦凡田贸易有限公司行政非诉 | needs_human |
| excel_candidate__live_commerce_ad__6faab3d4 | 行政 | （2018）冀0981行初14号 | 河北溪林塑业有限公司与泊头市市场监督管理局行政案 | needs_human |
| excel_candidate__live_commerce_ad__a298aa7b | 行政 | （2016）浙0204行审22号 | 宁波市市场监督管理局与宁波广发文博虫草制品科技有限公司非诉执 | needs_human |
| excel_candidate__live_commerce_ad__a6165916 | 行政 | （2017）豫1528行审92号 | 息县工商管理和质量技术监督局与息县广播电视台非诉执行审查案 | needs_human |
| excel_candidate__medical_beauty_device_guarantee__333bec1e | 行政 | （2021）苏03行终63号 | 徐州宇彤医疗器械有限公司第一分公司与徐州市泉山区市场监督管理 | needs_human |
| excel_candidate__medical_beauty_device_guarantee__70220379 | 行政 | （2019）冀0203行初302号 | 唐山煤医整形美容医院与唐山市路北区市场监督管理局行政案 | needs_human |
| excel_candidate__medical_beauty_device_guarantee__b8bc4386 | 行政 | （2019）辽02行终627号 | 大连市金州区中医医院与大连市市场监督管理局行政案 | needs_human |
| excel_candidate__medical_beauty_device_guarantee__c5e4983d | 行政 | （2018）琼0105行初169号 | 海南伊佳医疗美容医院有限公司与海口市龙华区工商行政管理局行政 | needs_human |
| excel_candidate__medical_beauty_device_guarantee__d3aee945 | 行政 | （2018）鄂0103行审20号 | 武汉市工商行政管理局、武汉广播广告传播有限公司非诉执行审查案 | needs_human |
| excel_candidate__native_health_ad__1a078812 | 行政 | （2019）川2021行审14号 | 安岳县市场监督管理局与安岳县康寿源健康生活馆行政非诉审查案 | needs_human |
| excel_candidate__native_health_ad__6a75abb1 | 行政 | （2017）鄂0103行审32号 | 武汉市工商行政管理局与武汉广播广告传播有限公司非诉执行审查案 | needs_human |
| excel_candidate__native_health_ad__8cc0903c | 行政 | （2019）鄂1002行审4号 | 荆州市工商行政管理局与荆州电视台非诉执行审查案 | needs_human |
| excel_candidate__native_health_ad__b4f965f5 | 行政 | （2017）鄂0103行审86号 | 武汉市工商行政管理局与武汉长江日报传媒集团有限公司武汉晨报分 | needs_human |
| excel_candidate__native_health_ad__b7aba4b2 | 行政 | （2017）鄂0103行审61号 | 武汉市工商行政管理局与武汉电视广告传媒有限公司非诉执行审查案 | needs_human |
| excel_candidate__native_health_ad__e805d0c6 | 行政 | （2019）浙0603行初180号 | 绍兴上虞康强医疗器械经营部与绍兴市上虞区市场监督管理局行政案 | needs_human |
| excel_candidate__real_estate_misleading__39aefb2d | 行政 | （2025）粤20行终552号 | 中山某有限公司与某街道办行政案 | needs_human |
| excel_candidate__real_estate_misleading__9d4cd311 | 行政 | （2024）鲁1302行审499号 | 临沂市市场监督管理局与某某（临沂）地产开发有限公司非诉执行审 | needs_human |
| excel_candidate__real_estate_misleading__b7d7fead | 行政 | （2025）新0203行审17号 | 克拉玛依市克拉玛依区市场监督管理局与新疆某甲房地产开发有限公 | needs_human |
| excel_candidate__real_estate_misleading__c09b9f5e | 行政 | （2025）鲁0215行审189号 | 青岛市即墨区某局与青岛某有限公司行政非诉审查案 | needs_human |
| excel_candidate__real_estate_misleading__c2ee21d5 | 行政 | （2025）渝0109行审15号 | 重庆市北碚区市场监督管理局与重庆某房地产开发有限公司非诉执行 | needs_human |
| excel_candidate__real_estate_misleading__c7de0984 | 行政 | （2025）川1322行审9号 | 营山县市场监督管理局与营山某商贸有限公司行政非诉审查案 | needs_human |
