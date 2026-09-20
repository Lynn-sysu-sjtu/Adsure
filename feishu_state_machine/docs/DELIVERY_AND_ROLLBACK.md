# Adsure 新功能交付与回退说明

本交付以本地功能分支为准。代码、离线测试和交付包已准备；本轮未启动真实服务，未连接真实飞书、规则引擎、OCR、案例库或其他外部服务，未修改线上数据，也未推送远程仓库。

## 基准与本地检查点

| 检查点 | 提交 |
| --- | --- |
| 卡片修复后的功能开发基准 | `0e3bf9525eaedb7928f04bf697c68b5b72fb420e` |
| SQLite 追加结构与部署开关 | `c4374ede8a0fb3bf551fa313bb605a421b0b69b1` |
| 诊断标识与外部异常脱敏 | `ba2b03189c2c7424fc22b8d47e3f5f2257081d00` |
| 审核时间线 | `86fcc36dd2c64716677fd09acd7ebe6a1f8ee539` |
| 法务卡片联动与审核版本 | `872a62280ecd784119c65434236af7aba2df84a4` |
| 卡片投递任务中心 | `c2bdf954f351b44e746169721646a9ff14a76c7a` |
| 可开关的合规记忆中心 | `9552f7227afbd6363b1d74bdb5d4f522e8280cdd` |

基准标签为 `baseline-card-fix-before-new-features`。基准提交只包含开发前已经修改的 `card_action_service.py`、`tests/test_card_action_service.py` 和 `tests/test_job_runtime.py`，保留了：

- `start_ai_review` 与 `skip_review` 共用 `initial-choice`；
- `confirm_mode` 继续使用独立的 `mode-confirm`；
- `escalate_to_legal` 继续使用 `legal-route`；
- `resubmit` 继续使用独立的 `resubmit`。

## 四项功能与独立关闭

所有部署开关缺失或不是布尔值 `True` 时均视为关闭。

| 功能 | 配置 | 关闭后的行为 |
| --- | --- | --- |
| 审核时间线 | `ADSURE_AUDIT_TIMELINE_ENABLED=False` | 不写入公开业务时间线事件，也不显示时间线；详情与原审核流程继续运行，其他功能的内部维护事件不受影响 |
| 法务卡片联动 | `ADSURE_LEGAL_CARD_SYNC_ENABLED=False` | 不再创建卡片更新投递；法务裁决和运营通知照常 |
| 投递任务中心 | `ADSURE_OPS_ENABLED=False` | 页面和 API 均返回 404；worker 和原投递照常运行 |
| 合规记忆能力 | `ADSURE_MEMORY_CENTER_AVAILABLE=False` | 设置 API 和 UI 不存在；审核走无记忆路径 |

投递中心还必须同时设置非空的 `ADSURE_OPS_USERNAME` 与 `ADSURE_OPS_PASSWORD`，否则仍返回 404。密码只来自服务器配置，不进入数据库、日志、HTML 或 JavaScript。

`ADSURE_MEMORY_CENTER_AVAILABLE` 只决定能力是否可用。SQLite 设置 `memory_center_enabled` 决定审核读取开关，缺失、无效或读取失败均按 OFF；默认 OFF。无论 ON 或 OFF，新的 `refine`/`override` 纠正仍按原逻辑沉淀。

## SQLite 增量迁移

现有 `ADSURE_DB_PATH` 初始化时会：

- 使用 `CREATE TABLE IF NOT EXISTS` 增加 `app_settings` 和 `audit_events`；
- 为 `audit_events` 增加 `(record_id, created_at, id)` 索引；
- 通过 `PRAGMA table_info` 检查 `deliveries.replay_count`，只在缺列时执行一次 `ALTER TABLE ... ADD COLUMN ... DEFAULT 0`。

迁移不重建表，不改名或删除列，不批量改写旧数据，不改变已有 job、delivery、轮次、状态和幂等键，也不迁移、清理或暂停 `data/corrections.json`。关闭或回退功能时保留追加表、列和历史事件，旧代码可安全忽略。

## 功能行为摘要

### 投递任务中心

- `/ops/deliveries` 及对应 API 仅在功能开启且 Basic Auth 配置完整时存在，不在普通工作台或飞书卡片中提供入口。
- 列表在 SQL 查询边界完成分页与筛选，只返回业务化类型、脱敏接收人和脱敏消息编号，不返回 payload、幂等键、卡片 JSON、原始错误或凭据。
- 手动重新发送只允许“终止失败且没有 message_id”的投递，并在 `BEGIN IMMEDIATE` 中条件更新同一行；保留 delivery id、payload、max attempts、幂等键和稳定 UUID，只增加 `replay_count`。
- 重复请求只有第一次成功；维护操作写入内部事件，不进入普通审核时间线。

### 法务卡片联动

- 新页面提交不透明 `review_version` 和 `review_intent`；首次裁决、修改裁决、模糊写入恢复和缺少版本的旧调用分别保留既定语义。
- 旧版本提交会正常结束为 stale，且不写业务字段、不增加驳回次数、不保存纠正、不通知运营、不更新法务卡；网页自动刷新并仅显示自然提示。
- 一次有效裁决会为同记录、同轮次、已经成功送达的每张法务卡建立独立持久更新投递。某一张失败只由原有限重试处理，不回滚裁决，不影响其他卡。
- 延迟恢复发送的法务卡会先读取最新状态；本轮已经完成时直接发送完成状态卡。
- 延迟卡片联动钩子本身失败时会直接降级为发送原法务卡；同毫秒、同裁决但审核人或批注不同的旧版本任务不会被误认成当前任务的模糊成功恢复。

### 审核时间线

- 审计只在真实业务节点确定后追加，以业务轮次与任务/投递标识构造稳定事件键；worker 重试不会重复展示。
- 普通接口使用事件 allowlist 并转换成简短中文，只返回展示字段；内部同步、维护重发、job/delivery id、事件键、原始摘要和内部记录标识均不返回。
- 页面异步加载，使用安全 DOM API，并以本地请求序号阻止快速切换时旧响应覆盖新记录；读取失败仅让该区域安静降级。
- 审计写入失败只记录后台诊断，不会令审核、裁决或卡片投递失败。
- 时间线薄接入和路由注册即使直接异常，也只降级该功能，不会阻断卡片动作、worker 业务任务或工作台启动。

### 合规记忆中心

- 可用性开启后，“规则沉淀库”显示带键盘和触摸支持的开关；零记录时仍显示。设置请求期间禁用，结果不确定时只执行一次 GET 确认。
- OFF 时每次审核只读取一次设置，之后不检索、不注入、不增加模型调用；新的法务纠正仍继续沉淀。
- ON 时只检索同一行业、active、最多三条。候选列表路径复用既有 LLM 调用；完整结果路径最多增加一次可选修正调用。
- 修正输入以不可信 JSON 边界传递；输出按允许字段、类型、合法路由和候选 ID 校验。超时、异常或无效输出均无感回退原结果，并保留保护字段和未知兼容字段。
- 候选列表路径仍只复用一次原有模型调用；返回结果会去除记忆内部措辞、候选编号及原样复述的较长历史片段。纠正列表接口使用公开字段清单，不返回记录编号、幂等键或未知存储字段。
- 记忆入口或路由注册直接异常时同样回退无记忆路径；如果失败来自原有 LLM 本身，则仍保留原失败与有限重试语义，不吞错也不重复调用。

## 建议部署步骤（本轮不执行）

1. 停止服务器现有三个进程。
2. 单独备份服务器自己的 `config.py` 和整个 `data/` 运行数据目录。
3. 将交付包解压到新的发布目录，只同步代码和静态业务资源；不要覆盖或删除服务器旧目录。
4. 恢复服务器自己的 `config.py`、SQLite 文件和 `data/corrections.json`。
5. 确认服务器虚拟环境满足 `requirements.txt`；不要使用备份目录里不完整的虚拟环境。
6. 先保持四个新功能开关全部关闭，启动后让现有 SQLite 自动执行追加迁移，并检查原审核流程。
7. 在受控测试物料上完成真实飞书验收：开始审核、三种模式、跳过 AI、主动转法务、重新提交、六种法务组合、修改裁决和多法务卡联动。
8. 按“时间线 → 法务卡联动 → 投递中心 → 记忆能力可用性”逐项开启；记忆运行开关仍保持 OFF，直到人工确认纠正记录。
9. 检查 systemd 或其他启动配置是否仍引用旧 `reliable_overlay/`。本轮保留该目录原文件，但未修改、未接入主业务，也未纳入交付包；未确认引用关系前不要删除。

投递中心启用时应位于 HTTPS 和受限维护网络后方。

## 回退

### 独立快速止损

优先关闭对应部署开关并重启原有进程。四项开关互不依赖；不需要删除数据库追加结构。

法务卡联动完整回退前：

1. 先设置 `ADSURE_LEGAL_CARD_SYNC_ENABLED=False`，停止产生新联动投递。
2. 停止服务并检查是否仍有等待或正在租用的“法务卡片完成更新”投递。
3. 优先等待这些可选投递结束，再回退代码。
4. 不删除投递记录，不回滚已经完成的法务业务裁决。

### 单项代码回退

四个 feature 提交已经从最终候选版本分别用普通 `git revert --no-edit <提交>` 验证，可各自独立移除，不要求先回退其他功能：

- 时间线：`git revert --no-edit 86fcc36dd2c64716677fd09acd7ebe6a1f8ee539`
- 法务卡片联动：`git revert --no-edit 872a62280ecd784119c65434236af7aba2df84a4`
- 投递任务中心：`git revert --no-edit c2bdf954f351b44e746169721646a9ff14a76c7a`
- 合规记忆中心：`git revert --no-edit 9552f7227afbd6363b1d74bdb5d4f522e8280cdd`

每次回退都应在新本地分支或新发布目录执行并重新跑编译与剩余测试。只有四项功能都已移除后，才考虑依次回退诊断脱敏提交 `ba2b03189c2c7424fc22b8d47e3f5f2257081d00` 和公共追加结构提交 `c4374ede8a0fb3bf551fa313bb605a421b0b69b1`；通常保留这些向后兼容的安全与追加结构更稳妥。

完整回到基准的低风险方式，是从标签 `baseline-card-fix-before-new-features` 创建一个全新发布目录或新本地分支，再恢复服务器自己的 `config.py` 与 `data/`。不要在运行目录强制重置，也不要删除迁移后的数据库结构。

## 日志与用户提示边界

本轮新增结构化日志保留业务阶段、哈希脱敏后的记录/幂等/请求标识、任务或投递编号、错误分类和恢复结果；不记录密钥、Token、完整 open_id、完整 message_id、完整卡片、完整物料、纠正原文或原始外部响应。

普通用户界面只使用固定的简短文案。自动重试、版本判断、任务/投递状态、内部 ID、错误码、堆栈和原始服务端消息不进入卡片、时间线、表单提示或 toast。可选能力失败优先无感降级；只有确实需要重新操作时才显示一句普通提示。

## 离线验证记录

2026-09-02 在本地候选版本完成以下检查，所有外部边界均使用 mock：

- 功能开发前基准：原有 40 项测试全部通过；
- `python3 -m unittest discover -s tests -v`：107 项全部通过；
- `node --check`：`static/main.js`、`static/timeline.js`、`static/ops_deliveries.js`、`static/memory_center.js` 全部通过；
- `node tests/frontend_security_test.js`、`node tests/timeline_frontend_test.js`、`node tests/memory_frontend_test.js`：全部通过；
- 全项目 Python 编译检查通过（排除 `.git`、虚拟环境、旧 overlay 和运行数据）；
- `bash -n start.sh start_local.sh stop.sh` 通过；
- `git diff --check` 通过；
- 单项功能普通回退后的编译、剩余 Python 测试和剩余前端测试全部通过：时间线 98 项、法务联动 93 项、投递中心 99 项、记忆中心 79 项；
- 四项功能的全部 24 种连续回退顺序均无冲突，最终文件树一致；代表性全回退版本的 48 项 Python 测试及全部适用静态检查通过；
- 普通用户可见源码扫描未发现新增的异常串接、堆栈、`alert()`、原始服务端消息或内部记录标识展示。

测试中故意制造的外部异常会出现在测试进程的后台日志；相应断言确认这些原始内容不会进入网页、卡片、toast 或普通 API。

## 交付包边界

代码包从最终 Git 检查点使用 `git archive` 生成，只包含受版本控制的源代码、模板、CSS、JavaScript、测试、文档和静态业务资源。包内保留：

- `data/regulations.json`、`data/violations.json`；
- 项目自带 CSV/XLSX 模板；
- 正常源代码、HTML 模板、CSS、JavaScript、测试和本说明。

交付包排除 `.git`、`.pids`、`config.py`、`config.py.save`、`.env`、虚拟环境、日志、缓存、`__pycache__`、`.pytest_cache`、SQLite/WAL/SHM、`data/corrections.json`、临时数据、`docs/test.txt`、`data/reliable_overlay/` 和旧 `reliable_overlay/`。文件清单和 SHA-256 与压缩包分开提供。
