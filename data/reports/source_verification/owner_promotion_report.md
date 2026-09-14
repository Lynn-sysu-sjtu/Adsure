# 业主审批入生产报告（115 条）

> 生成时间：2026-09-15T03:48:31+08:00（Asia/Shanghai）

## 决定

用户指令（2026-09-15）：取消硬红线核验门槛，**基本确定真实性的全部入生产**。据此对 115 条候选执行业主审批入产。随后用户指定将“罗技侮辱消费者广告处罚案”（沪市监静处〔2026〕062026000257号，处罚对象为罗技分销商上海百事得电子有限公司）一并入库，由 demo-only 转为正式生产案例（合计 116 条）。随后用户指示将检索到的两条同类案例（绝味食品2017双11低俗广告案、Ubras“躺赢职场”内衣广告案）**直接入生产库**（合计 118 条）。

## 执行内容

1. **数据**：115 条候选 JSON 增加 `owner_approval` 审批块（approved=true / approved_by=项目负责人 / override_source_verification=true），置 `approved_for_rag=true`、`review_status=approved`；**保留 `source_verification_status=pending_source_lookup`，不谎称 `source_verified`**；`original_decision_url` 保持 null。

2. **字段补全（非编造）**：97 条补 `raw_text_path`（DOCX/Excel 原始文本路径）；11 条补 `illegal_claims`、52 条补 `violation_type`（从各自 `facts_summary`/`risk_dimensions` 派生）；新增 `data/raw_text/case_library_xlsx__40个十大类违法广告行政处罚案例汇总表.json` 作为 Excel 原始文本回溯。

3. **生产副本**：115 条复制到 `data/structured/`（带 `source_record_path` 溯源 + `promotion` 标记），使 production 检索可解析。

4. **管线**：`src/build_chunks.py` 新增显式 `owner_approval_override`（仅带完整审批块的记录可跳过 source_type/source_url/source_verified 门槛；无审批块的候选仍被排除）；重建 `data/chunks/production_chunks.json`（254 chunks / 127 case_ids，含 115 条）与 `data/chunks/production_semantic_index.json`。

5. **契约/校验**：`validate_cases.py`、`validate_audit_cases.py`、`validate_judge_acceptance.py` 对业主审批记录加显式例外；`adapt_case` 响应新增 `owner_approved` 字段；相关测试同步更新并全部通过（156 项中 155 项通过，唯一失败为与本次无关的既有 video 测试）。

## 验证结果

- production 检索可解析 115/115；三条评委查询首条命中不变。

- 抽样查询（美妆医疗用语 / 保健食品会销 / 游戏充值）返回 promoted 案例，`approved_for_rag=true`、`owner_approved=true`、`source_verification_status=pending_source_lookup`。

## 残留风险（务必知悉）

1. 115 条**没有官方处罚决定原文 URL**（`original_decision_url=null`），RAG 检索结果无法回溯到政府原文，只能回溯到内部 DOCX/Excel 原文（`raw_text_path`）。

2. 25 条民事案件（毛冉冉系列、游戏充值纠纷等）本质是司法参考，**没有行政处罚决定书**，作为“处罚案例”进入生产可能误导下游核验，建议前端/下游按 `case_nature` 过滤标注。

3. 45 条含「某/某某」匿名的当事人（如“重庆某生物科技”），`party_name` 不完整，命中后需人工确认主体。

4. 法条映射（`mapped_rule_ids`）多为候选推断，`legal_basis_provenance.specific_articles_published_by_case_source=false`，仍待法务复核。

## 回滚

- 候选：删除 115 条的 `owner_approval`，置回 `approved_for_rag=false`、`review_status=pending_review`；删除 `data/structured/` 下 115 条副本；重跑 `python3 src/build_chunks.py` 与语义索引即可回到入产前状态。

## 文件

- 审批清单：`data/reports/source_verification/owner_promotion_manifest.json`

- 明细（含 promoted 标记）：`data/reports/source_verification/verification_details.jsonl`

## 补充：罗技案入库说明（2026-09-15）
- 检索核实：媒体一致报道“罗技广告被罚20万”；处罚决定书全文（用户提供）明确处罚对象为**罗技（中国）科技有限公司分销商「上海百事得电子有限公司」**（运营抖音号「罗技」/LogitechChina 与「罗技G官方旗舰店」），处罚机关为上海市静安区市场监督管理局，文号沪市监静处〔2026〕062026000257号，罚款20万元（从轻），依据《广告法》第三、九（七）、五十七（一）条。
- 官方原文 URL 未公开索引到（搜狗/必应无 gov.cn 命中），`source_url` 暂为公众号线索，`source_verification_status` 保持 `pending_official_source_lookup`，不谎称 `source_verified`。
- 该案由 demo-only（not_for_production_factual_use）转为正式生产案例：owner_approval 入产、2 个 production chunk、可被“一降价像狗一样跑过来”文案召回。

## 补充2：同类案例直接入生产（2026-09-15）
- 新增 `juewei_2017_1111_lowbrow_ad_case`：绝味食品2017年“双11”低俗广告案。要素较全（处罚机关=长沙市工商行政管理局、金额60万、法条=广告法九(七)、决定书2017-12-22下发），均来自绝味食品公告与媒体报道转引，决定书号未核到。
- 新增 `ubras_2021_lingering_in_workplace_ad_case`：Ubras“让女性轻松躺赢职场”内衣广告案。金额87万为媒体口径；**处罚机关、决定书号、决定日期均未核到，保持空值，不编造**。
- 两条均为 `credible_secondary_source_only` + `owner_approval` 入产；`original_decision_url=null`；法条为推断（`inferred_pending_legal_review`）；risk_dimensions 用允许集（违背社会良好风尚/侮辱消费者）。
- 原广告词“我们一降价，你还不是像狗一样跑过来”重跑：production 仍只召回罗技案（词面不含降价/狗，绝味/Ubras 不参与该查询）；用各自场景查询可召回（绝味/躺赢职场）。
