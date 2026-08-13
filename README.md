# 审心 · 广告合规审核系统 — AI 开发者上下文文档

> 本文档供 AI 助手（Claude / Copilot 等）在新会话中快速恢复项目上下文，直接继续开发。
> 人类开发者请阅读 `CLAUDE.md` 了解整体规格，阅读 `docs/` 了解产品设计。

---

## 项目一句话

MCN / 品牌方的广告物料合规审核工具。运营在飞书多维表格提交物料 → AI 审核 → 法务人工复核 → 结果回写表格。全程在飞书内闭环，无需另开工具。

---

## 一、系统架构（三进程）

```
飞书多维表格（v4，字段分5段）
        │
        │  worker.py 每5秒轮询，发现新行
        ▼
运营收到飞书互动卡片「开启AI审核」
        │
        │  运营点击 → 飞书 WebSocket 回调
        ▼
bot_listener.py  ← 长连接监听卡片事件
        │
        │  调用 predictor.execute()
        ▼
predictor.py（核心审核逻辑）
  1. build_context()   — 从多维表格读物料，OCR 附件图片
  2. call_teammate_engine()  — POST 到队友规则引擎 API
  3. call_llm()        — 若引擎只返回命中列表，调 LLM 生成六段报告
  4. write_back()      — 结果写回多维表格 ②③ 段
        │
        ├─ routing=待运营修改 → 向运营发「需修改」卡片
        └─ routing=待法务复核 → 向法务全员发通知卡片
                                  ↓
                              app.py（Flask 法务工作台）
                              法务在网页上裁决，结果写回④段
```

三个进程由 `start.sh` 统一拉起（崩溃自动重启），日志写 `logs/`。

---

## 二、关键文件速查

| 文件 | 职责 | 注意事项 |
|------|------|----------|
| `config.py` | 所有密钥和地址 | **不入库**，从 `config.example.py` 复制后填写 |
| `fields_v4.py` | v4 表格字段名常量 | 所有模块通过此文件引用字段，不要写死字符串 |
| `worker.py` | 轮询多维表格，向运营发审核触发卡片 | 含进程锁 + 磁盘去重（`/tmp/adsure_processed_ids.json`）|
| `bot_listener.py` | 飞书 WebSocket 长连接，卡片按钮回调 | 含进程锁；失败日志必须走 `sys.stderr, flush=True` |
| `predictor.py` | AI 审核核心：上下文构建→规则引擎→LLM→回写 | 兼容引擎返回 list 或完整 dict 两种格式 |
| `feishu_api.py` | 飞书 API 封装（token/bitable/IM/组织架构） | `get_dept_open_ids` 10分钟缓存；token 提前5分钟刷新 |
| `ocr_preprocessor.py` | 附件图片 OCR（腾讯云） | 若 `TENCENT_SECRET_*` 未配置则跳过 |
| `preference_memory.py` | 法务纠正记录 few-shot 注入 | 数据存 `data/corrections.json`，bigram 召回 top-3 |
| `app.py` | 法务工作台 Flask 后端，5001 端口 | 同时处理飞书卡片 challenge 验证 |

---

## 三、多维表格字段结构（v4，五段）

```
① 运营提交段   — 物料内容、行业领域、附件、提交人/时间、紧急程度
                  行业专属：美妆/游戏/保健食品各有独立字段组
② AI预审段     — 风险等级、命中要点、修改建议（运营可见，AI填写）
③ AI审核段     — 审核模式、审核意见（六段式）、高风险词、违规类型、推荐风险等级（法务可见）
④ 法务裁决段   — AI意见评价、物料裁决、异议字段、补充理由、最终修改意见
⑤ 流转沉淀段   — 当前状态、反馈类型、驳回次数、轮次
```

`⑤流转·当前状态` 的值是驱动整个状态机的核心：

| 状态值 | 触发方 | 含义 |
|--------|--------|------|
| `""` (空) | 运营在飞书填表 | 新提交，worker 检测到后发卡片 |
| `运营起草` | worker 发完卡片 / 错误回退 | 已通知运营，等待点击 |
| `AI预审中` | `_run_execute` 开始时写入 | 防重复触发 |
| `待法务复核` | `write_back()` 写入 | 进法务队列 |
| `待运营修改` | `write_back()` 写入 | 退回给运营修改 |
| `已通过` / `需修改` | 法务通过 app.py 操作 | 终态 |

---

## 四、规则引擎接口约定

`predictor.call_teammate_engine()` 向队友规则引擎 POST：

```json
{
  "record_id":        "飞书记录ID",
  "industry":         "美妆 | 游戏 | 保健食品",
  "content":          "物料文字内容（已含OCR结果）",
  "platform":         ["抖音", "小红书"],
  "material_type":    "图文 | 短视频 | ...",
  "product_category": "护肤 | MMO | 维生素/矿物质 | ...",
  "urgency":          "普通 | 加急",
  "supplement":       "运营补充的背景资料",
  "extras":           { "行业专属字段": "值" },
  "mode":             "极速 | 标准 | 深度"
}
```

**引擎可返回两种格式，predictor 均已兼容：**

```python
# 格式A：命中规则列表（当前引擎实际返回格式）
[
  {
    "rule_id": "GAME-FALSE-004",
    "rule_type": "游戏",
    "law_name": "《网络游戏管理暂行办法》",
    "violation_type": "虚假宣传",
    "default_routing": "法务"  # 或 "运营" / "运营补资料"
  }
]

# 格式B：完整审核结果（引擎后期可直接返回，跳过本地LLM）
{
  "routing": "法务 | 运营",
  "预审_风险等级": "高 | 中 | 低",
  "预审_命中要点": "...",
  "审核_审核意见": "六段式报告",
  "审核_高风险词命中": "...",
  "审核_推荐违规类型": ["虚假宣传"],
  "审核_推荐风险等级": "高",
  ...
}
```

接口地址：`POST {RULE_ENGINE_URL}`（config.py 中配置，已拼好 `/audit` 路径）。

---

## 五、LLM 调用

- 使用 `anthropic` SDK，支持 base_url 中转
- System prompt 包含：角色定义 + 物料上下文 + 规则引擎命中规则 + few-shot 法务纠正案例
- 输出要求：严格 JSON，包含 `预审_*` 和 `审核_*` 字段
- 当前已移除 `审核_平台规则预检` 字段（LLM 填写质量差，2026-08 废弃）
- LLM 超时：规则引擎 20s，LLM 调用无显式超时（由 anthropic SDK 控制）

---

## 六、已知问题与修复状态

| 问题 | 状态 | 位置 |
|------|------|------|
| 法务通知静默失败（send_card_to 返回值被丢弃） | **已修复** | `bot_listener._send_card_to` 现在返回 bool，`_notify_legal` 追踪失败并走 stderr |
| 法务通知失败后仍发虚假"成功流转"通知给运营 | **已修复** | `_run_execute` 检查 `_notify_legal` 返回值，失败则调 `_on_audit_error` |
| stdout 在 journald 环境下块缓冲不可见 | **已知，部分缓解** | 重要失败日志已改用 `sys.stderr, flush=True`；普通 print 仍存在缓冲 |
| worker 重复发卡（重启后去重状态丢失） | **已修复** | 去重 ID 持久化到 `/tmp/adsure_processed_ids.json` |
| 规则引擎 Read timed out | **外部问题** | 规则引擎服务假死，联系队友排查 |
| 运营漏收"确认审核模式"卡片 | **设计决策，非 Bug** | `cc3a81e` 故意移除了三步流程中的模式确认卡片，现在运营只需两步；`_send_mode_card` 是死代码但保留未删 |
| `_run_escalate` 中 `_notify_legal` 失败不处理 | **已知遗留** | 运营手动升级转法务时，通知失败无回退，低优先级待修 |

---

## 七、部署环境

- **服务器**：`124.223.111.170`（腾讯云轻量）
- **服务管理**：systemd，单元名 `adsure-bot-listener.service`
- **日志查看**：`journalctl -u adsure-bot-listener -f`（stderr 实时）；`tail -f logs/bot_listener.log`（stdout，有缓冲延迟）
- **本地路径**：`/root/Adsure/`
- **云端 HEAD**：本地 `feishu-workbench` 分支比云端多若干 commit，需 `git push` 后在服务器 `git pull && systemctl restart`

---

## 八、config.py 必填项（不入库）

```python
RULE_ENGINE_URL     = "http://IP:端口/audit"   # 队友规则引擎
RULE_ENGINE_API_KEY = "..."
CASE_ENGINE_URL     = "http://IP:端口/rag"     # 队友案例库（暂未接入）
CASE_ENGINE_API_KEY = "..."
LLM_API_KEY         = "..."                    # Anthropic 格式
LLM_BASE_URL        = "https://..."
LLM_MODEL           = "claude-opus-4-6"
TENCENT_SECRET_ID   = "..."                    # OCR，可留空跳过
TENCENT_SECRET_KEY  = "..."
FEISHU_APP_ID       = "cli_..."
FEISHU_APP_SECRET   = "..."
BITABLE_APP_TOKEN   = "..."                    # 多维表格 URL 中的 token
BITABLE_TABLE_ID    = "tbl..."
WORKBENCH_URL       = "http://IP:5001"         # 法务工作台公网地址
LEGAL_DEPT_NAME     = "法律与合规"             # 飞书组织架构中法务部门名称
LEGAL_OPEN_IDS      = ["ou_..."]               # 兜底列表，组织架构查不到时使用
```

---

## 九、待开发 / TODO

按优先级排列：

1. **`_run_escalate` 失败处理**：运营手动升级转法务时，若 `_notify_legal` 失败，应回退状态并通知运营，目前无处理
2. **`stdout` 全面换 stderr+flush**：`bot_listener.py` 和 `worker.py` 中所有重要 print 都应改为 `sys.stderr, flush=True`，防止 journald 缓冲丢日志
3. **规则引擎超时重试**：规则引擎偶尔超时（20s），目前直接抛异常回退，可考虑加一次重试
4. **`审核_备案核查结果` 真实接入**：目前硬编码"MVP阶段暂未接入"占位
5. **`_send_mode_card` 死代码清理**：`cc3a81e` 移除了三步流程，但 `_run_prepare` 和 `_send_mode_card` 函数未删，如确认不恢复可删除
6. **法务工作台分页**：`app.py` 目前一次拉取全部记录，记录多时性能差
7. **preference_memory 向量化**：目前用 bigram 相似度检索，可升级为向量嵌入（Chroma/Milvus）

---

## 十、快速启动（本地开发）

```bash
# 1. 准备配置
cp config.example.py config.py  # 填入真实密钥

# 2. 安装依赖
pip3 install -r requirements.txt
pip3 install lark-oapi anthropic

# 3. 启动所有服务
./start_local.sh   # 前台运行，实时日志

# 或后台运行
./start.sh
tail -f logs/bot_listener.log

# 停止
./stop.sh
```

---

## 十一、git 历史关键节点

| commit | 内容 |
|--------|------|
| `v1.0` (tag) | 法务通知修复前的稳定快照，可回滚基准 |
| `7b46a11` | fix: 法务通知停止静默失败（当前线上版本基础） |
| `a0675b6` | fix: worker 持久化去重 + 进程互斥锁 |
| `cc3a81e` | fix: 去掉模式确认卡片，运营从3步变2步（`_send_mode_card` 变死代码） |
| `ef3049f` | chore: 收拢所有本地改动快照（当前 HEAD） |
