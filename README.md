# 审心 · 广告合规审核系统 — 开发者交接说明

> 本文档面向拿到本代码包的队友，说明各文件用途、系统架构、以及启动前必须填写的配置项。

---

## 一、系统架构概览

```
运营在飞书多维表格填写物料
        ↓
    worker.py（轮询扫表，创建持久任务）
        ↓
  运营点「开启AI审核」按钮
        ↓
  app.py / bot_listener.py（HTTP / WebSocket 回调适配）
        ↓
  card_action_service.py（统一动作、幂等入队）
        ↓
  SQLite 持久任务/投递队列（worker 单实例消费）
        ↓
    predictor.py（规则引擎 → LLM → 回写多维表格）
        ↓
  结果写入飞书多维表格 ②③ 段字段
        ↓
  法务收到飞书通知卡片 → 打开工作台裁决
        ↓
    app.py（法务工作台 Web 界面，Flask）
```

三个进程由 `start.sh` 统一拉起；HTTP/WebSocket 入口只负责受理，持久任务由唯一的 `worker.py` 消费。

---

## 二、文件速查表

### 核心服务（必须运行）

| 文件 | 职责 |
|------|------|
| `worker.py` | 每5秒轮询新提交，并作为唯一持久任务/投递消费者处理审核与通知 |
| `bot_listener.py` | 飞书 WebSocket 长连接适配器，只解析动作并调用统一动作服务 |
| `app.py` | 法务工作台与 HTTP 卡片回调适配器；裁决使用幂等持久任务 |
| `predictor.py` | AI审核核心：读多维表格字段 → 调规则引擎 API → 调 LLM → 回写审核结果 |
| `card_action_service.py` | HTTP/WebSocket 共用的卡片动作入口与业务幂等策略 |
| `reliable_queue.py` | SQLite WAL 任务/投递存储、租约恢复、退避重试和唯一约束 |
| `job_runtime.py` | 审核、重提、转法务、裁决与逐收件人投递处理器 |
| `card_templates.py` | 保持原业务内容的集中卡片模板 |

### 基础设施

| 文件 | 职责 |
|------|------|
| `feishu_api.py` | 飞书 API 封装：获取 token、读写多维表格记录、查部门成员、发消息卡片、上传/下载附件 |
| `fields_v4.py` | v4 多维表格字段名常量集中管理，所有模块通过此文件引用字段名，避免写死字符串 |
| `config.py` | **需要自行创建**（见下节），所有密钥/地址在此集中配置 |
| `ocr_preprocessor.py` | 物料附件 OCR 处理：调腾讯云 OCR API 识别图片内文字，拼入 LLM 上下文 |
| `preference_memory.py` | 轻量规则沉淀：将法务纠正记录存入 `data/corrections.json`，下次审核时作为 few-shot 示例注入 LLM prompt |

### 飞书多维表格搭建脚本（一次性使用）

| 文件 | 职责 |
|------|------|
| `create_bitable_v4.py` | 一键建表：创建 v4 多维表格，自动添加全部字段、建字段分组 |
| `setup_form_v4.py` | 配置飞书多维表格的表单视图（运营提交入口） |
| `add_game_platform_options.py` | 追加「游戏·投放平台」字段的选项（补丁脚本，按需运行） |
| `cleanup_junk_fields.py` | 删除多维表格中多余的默认字段（建表后运行一次） |
| `add_field_background.py` | 给字段添加背景色（美化视图用，可选） |

### 诊断/工具脚本

| 文件 | 职责 |
|------|------|
| `get_legal_open_ids.py` | 遍历飞书组织架构，打印法务部门所有成员的 `open_id`，用于填写 `config.py` 中的 `LEGAL_OPEN_IDS` |
| `diagnose_permission.py` | 检查飞书应用的 API 权限是否开通正确 |
| `test_api_setup.py` | 快速验证飞书 API 连通性和多维表格读写是否正常 |
| `transfer_owner.py` | 将多维表格所有权转让给指定用户 |
| `resolve_wiki_token.py` | 处理飞书 Wiki 文档 token 的工具脚本 |

### 前端

| 文件 | 职责 |
|------|------|
| `templates/workbench.html` | 法务工作台 HTML 页面（Jinja2 模板） |
| `static/main.js` | 工作台前端交互逻辑 |
| `static/style.css` | 工作台样式 |

### 启动/停止

| 文件 | 职责 |
|------|------|
| `start.sh` | 一键后台启动三个服务（worker / bot_listener / app），崩溃自动重启，日志写入 `logs/` |
| `start_local.sh` | 本地开发用启动脚本（前台运行，方便看日志） |
| `stop.sh` | 停止所有由 `start.sh` 启动的进程 |

### 数据/文档

| 文件/目录 | 说明 |
|-----------|------|
| `data/regulations.json` | 本地法规条文数据（规则引擎本地占位使用） |
| `data/violations.json` | 违规类型定义数据 |
| `data/corrections.json` | 法务纠正记录（运行时自动生成，preference_memory.py 读写） |
| `docs/` | 产品说明文档、开发计划、运营表单设计等 |

---

## 三、启动前必须完成的配置

### 第一步：创建 config.py

```bash
cp config.example.py config.py
```

然后用编辑器打开 `config.py`，填入以下内容：

---

#### 【你负责填写】规则引擎（对接队友 API）

```python
RULE_ENGINE_URL     = "http://队友规则引擎的IP:端口"   # 调用时会拼接 /audit 路径
RULE_ENGINE_API_KEY = "队友给你的 API Key"
```

- 对应 `predictor.py` 中 `run_rule_engine()` 函数，提交物料内容后返回命中规则列表
- 接口格式参考：`docs/规则引擎对接_规则沉淀接口说明.md`

---

#### 【你负责填写】案例库（RAG 检索，对接另一位队友）

```python
CASE_ENGINE_URL     = "http://队友案例库的IP:端口"
CASE_ENGINE_API_KEY = "队友给你的 API Key"
```

---

#### 【你负责填写】LLM API

```python
LLM_API_KEY  = "你的 LLM API Key"
LLM_BASE_URL = "https://api.anthropic.com"   # 或中转站地址
LLM_MODEL    = "claude-opus-4-6"             # 或 deepseek-v4-pro 等兼容模型
```

- `predictor.py` 中 `call_llm()` 使用此配置，走 Anthropic 格式接口

---

#### 【你负责填写】飞书开放平台

```python
FEISHU_APP_ID     = "cli_xxxx"          # 飞书开发者后台 → 应用信息 → App ID
FEISHU_APP_SECRET = "xxxxxxxxxxxx"      # 飞书开发者后台 → 应用信息 → App Secret
```

获取方式：
1. 登录 [飞书开发者后台](https://open.feishu.cn/app)
2. 进入企业自建应用 → 凭证与基础信息
3. 复制 App ID 和 App Secret

需要开通的权限（在开发者后台 → 权限管理 中申请）：
- `im:message:send_as_bot`（发消息卡片）
- `bitable:app`（读写多维表格）
- `contact:contact.base:readonly`（查组织架构/法务成员）

---

#### 【你负责填写】飞书多维表格

```python
BITABLE_APP_TOKEN = "多维表格的 App Token"   # URL 中 /base/XXXXXX 的部分
BITABLE_TABLE_ID  = "表格 ID"               # URL 中 table=tblXXXX 的部分
```

如果还没有建表，运行以下命令一键建表：

```bash
python3 create_bitable_v4.py
```

建完后脚本会输出 `BITABLE_APP_TOKEN` 和 `BITABLE_TABLE_ID`，填入 `config.py` 即可。

---

#### 【可选填写】法务成员 open_id 兜底列表

```python
LEGAL_OPEN_IDS = [
    "ou_xxxxxxxxxxxxxxxx",   # 法务成员1
    "ou_yyyyyyyyyyyyyyyy",   # 法务成员2
]
```

系统优先通过飞书组织架构接口自动获取法务部门成员。若组织架构接口无权限，则使用此处的兜底列表。

获取 open_id 的方法：

```bash
python3 get_legal_open_ids.py
```

---

#### 【可选填写】腾讯云 OCR（仅当物料含图片附件时需要）

```python
TENCENT_SECRET_ID  = "AKIDxxxx"
TENCENT_SECRET_KEY = "xxxx"
TENCENT_OCR_REGION = "ap-guangzhou"
```

若不填，附件图片内容将被跳过，只审核文字内容。

---

#### 【按实际修改】法务工作台地址

```python
WORKBENCH_URL = "http://你的服务器IP:5001"   # 本地测试用 http://localhost:5001
```

此地址会出现在发给法务的飞书通知卡片中的「打开法务工作台」按钮里。

---

### 第二步：安装依赖

```bash
pip3 install -r requirements.txt
```

---

### 第三步：配置飞书应用的卡片回调地址

在飞书开发者后台 → 机器人 → 卡片请求网址，填入：

```
http://你的服务器IP:5001/feishu/card
```

`app.py` 在此路由处理运营点击卡片的回调。

回调校验采用兼容迁移开关。先在 `config.py` 填写飞书后台的 Verification Token 和 Encrypt Key，确认无误后设置：

```python
FEISHU_CALLBACK_VERIFY_ENABLED = True
```

开启后会校验签名与时间窗口；未配置完成前保持 `False` 不会突然阻断现有回调，但后台会记录安全告警。

---

### 持久任务存储

首次启动会自动创建 `data/adsure_jobs.sqlite3`，无需手工建表。请确保 `data/` 位于持久磁盘并可写，备份时同时备份该 SQLite 文件。SQLite 使用 WAL、`busy_timeout`、事务、唯一约束和任务租约：

- `/tmp/adsure_processed_ids.json` 只作为旧版本迁移痕迹读取，不再决定卡片是否已经送达；
- worker 是默认唯一消费者，进程中断后会恢复未完成及租约超时的任务；
- 法务多人通知按收件人独立记录，只重试失败者；
- 消息发送使用稳定 UUID，同一模糊超时重试不会创建新的本地投递。

相关参数均在 `config.example.py` 的 `ADSURE_*` 配置项中。回退旧版前，先停止三个进程并保留 SQLite 文件，以便恢复本轮尚未完成的任务。

本轮不需要新增或修改任何线上多维表格字段。升级时只需合并代码、补齐新增配置并安装 `requirements.txt`；首次启动会自动完成本地 SQLite 建表。若要回退，先停止三个进程、备份 `data/adsure_jobs.sqlite3*`，再恢复上一版源码；SQLite 备份应继续保留，确认没有待处理任务后再决定是否归档。

---

### 第四步：启动服务

```bash
# 服务器/后台运行
./start.sh

# 本地开发（前台运行，实时看日志）
./start_local.sh

# 停止
./stop.sh
```

---

## 四、核心数据流（给规则引擎对接方参考）

`predictor.py` 调用规则引擎的请求格式：

```
POST {RULE_ENGINE_URL}/audit
Authorization: Bearer {RULE_ENGINE_API_KEY}
Content-Type: application/json

{
  "text": "物料文字内容",
  "industry": "美妆 | 游戏 | 保健食品",
  "platform": "抖音 | 小红书 | ..."
}
```

期望返回（规则引擎响应中会解析以下字段）：

```json
{
  "risk_level": "高 | 中 | 低 | 无明显风险",
  "hit_points": "命中要点说明",
  "violation_types": ["绝对化用语", "虚假宣传"],
  "suggestions": "修改建议"
}
```

详细接口约定见：`docs/规则引擎对接_规则沉淀接口说明.md`

---

## 五、常见问题

**Q: worker 启动后无反应，表格有新记录但没有收到卡片？**
- 检查 `config.py` 中 `BITABLE_APP_TOKEN` / `BITABLE_TABLE_ID` 是否正确
- 运行 `python3 test_api_setup.py` 验证飞书 API 连通性
- 检查飞书应用是否开通了 `bitable:app` 权限

**Q: 运营收到卡片，点了「开启AI审核」但没有后续？**
- 检查飞书开发者后台的「卡片请求网址」是否填写了 app.py 的地址
- 查看 `logs/bot_listener.log`（动作受理）和 `logs/worker.log`（后台任务）中的结构化错误记录

**Q: 法务收不到审核通知卡片？**
- 检查 `LEGAL_DEPT_NAME` 是否与飞书组织架构中的部门名称**完全一致**
- 运行 `python3 get_legal_open_ids.py` 确认能否查到法务成员
- 若组织架构接口无权限，在 `config.py` 的 `LEGAL_OPEN_IDS` 中手动填入法务成员的 open_id

**Q: 规则引擎 Read timed out？**
- 规则引擎服务本身超时，与本项目代码无关，联系负责规则引擎的队友排查

---

*如有问题联系项目负责人。*
