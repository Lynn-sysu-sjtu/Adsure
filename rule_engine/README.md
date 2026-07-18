# Adsure Rule Engine

本目录用于存放 Adsure MVP 的规则引擎模块。规则引擎负责接收飞书状态机传入的审核请求，读取结构化规则库，完成规则召回、风险判断、LLM 审核意见生成，并把结构化结果返回给飞书侧回写。

## 当前模块定位

规则引擎不是单纯把广告文案直接交给大模型判断，而是采用：

```text
飞书字段输入
  -> 字段映射与入参校验
  -> 规则库加载
  -> content / fact / workflow 分层
  -> 关键词 / 正则 / 语义召回
  -> DeepSeek 审核判断
  -> 风险等级合成
  -> routing 输出
  -> 飞书回写
```

这种设计的目标是让审核结果可解释、可复核、可回归测试，避免 LLM 每次凭空生成不同规则。

## 建议上传目录结构

请将本地稳定版本整理为：

```text
rule_engine/
  src/
  jsonbase/
  schema/
  vectorbase/
  test_cases/
  test_reports/
  reports/
  requirements.txt
  README.md
```

其中：

- `src/`：规则引擎源代码。
- `jsonbase/`：当前可被引擎消费的结构化规则库，只放正式 `.json`，不要放 `.bak_*`。
- `schema/`：规则库 schema、请求 schema、响应 schema、飞书字段说明。
- `vectorbase/`：语义召回向量索引，例如 `rule_vector_index.json`。
- `test_cases/`：baseline 样例，例如 `rule_engine_cases_v0.1.json`。
- `test_reports/`：保留最新 baseline 报告即可。
- `reports/`：只保留当前协作需要的诊断结果，例如风险合成诊断、medium priority 规则质检清单。

## 关键脚本说明

| 文件 | 功能 |
|---|---|
| `src/audit_api.py` | FastAPI 入口，提供 `/audit`，校验 `X-API-Key`，统一返回 `code/msg/data` |
| `src/rule_engine.py` | 主审核链路：入参校验、规则召回、fact 补资料、风险合成、routing、输出组装 |
| `src/field_mapper.py` | 飞书字段映射，把飞书中文字段或扁平 JSON 转成规则引擎内部结构 |
| `src/kg_rule_store.py` | 加载 `jsonbase` 规则库 |
| `src/llm_judgment.py` | 构造 DeepSeek prompt，输出意见类型、风险等级、审核意见、规则引用 |
| `src/deepseek_client.py` | DeepSeek API 客户端 |
| `src/zhipu_embedding_client.py` | 智谱 embedding API 客户端 |
| `src/semantic_recall.py` | 语义召回逻辑 |
| `src/rule_vector_index.py` | 读取和使用向量索引 |
| `src/build_rule_vector_index.py` | 构建 `vectorbase/rule_vector_index.json` |
| `src/run_engine_baseline_eval.py` | 跑正式 baseline，生成评估报告 |
| `src/risk_synthesis_diagnostics.py` | 诊断风险等级合成问题 |
| `src/legal_attention_calibration.py` | 生成 legal_attention / routing 校准建议 |
| `src/apply_legal_attention_calibration.py` | 将确认后的校准结果写回规则库 |
| `src/legal_attention_medium_qc.py` | 生成 medium priority 人工审核清单 |
| `src/batch_label_trigger_layer.py` | 批量标注 `content / fact / workflow` |
| `src/batch_rewrite_vector_text_hyde.py` | 批量改写 `vector_text` |

## 不要上传的内容

以下内容不应提交到 GitHub：

```text
.env
.env.*
__pycache__/
*.pyc
*.log
*.bak_*
jsonbase_v0/
_extracted/
.claude/
真实 API Key
临时测试输出
本地虚拟环境 .venv/
```

较大的原始 PDF、历史加工材料、旧版备份规则库建议先不要进入代码仓库。后续如果需要保留，可使用网盘、对象存储或 Git LFS。

## 环境变量

真实密钥不要写入仓库。仓库根目录已有 `.env.example`，本地或云端需要自行创建 `.env` 或 systemd 环境变量。

常用变量包括：

```text
ADSURE_API_KEY
DEEPSEEK_API_KEY
ZHIPUAI_API_KEY
RULE_ENGINE_URL
```

## 本地启动

进入规则引擎源码目录后启动：

```powershell
cd rule_engine/src
python -m uvicorn audit_api:app --host 0.0.0.0 --port 8504
```

本地测试接口：

```text
POST http://127.0.0.1:8504/audit
Header: X-API-Key
```

浏览器直接打开 `/audit` 显示 `Method Not Allowed` 是正常的，因为该接口只接受 POST 请求。

## 推荐测试

在 `rule_engine/src` 下运行核心单元测试：

```powershell
python -m unittest test_rule_engine_mvp.py test_semantic_recall.py test_rule_engine_llm_payload.py test_audit_api_auth.py
```

如果修改了召回、向量索引、routing 或风险等级合成策略，需要重跑 baseline：

```powershell
python run_engine_baseline_eval.py
```

## 与飞书状态机的接口边界

规则引擎对飞书返回统一结构：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {}
}
```

失败时：

```json
{
  "code": -1,
  "msg": "错误原因",
  "data": null
}
```

飞书侧根据 `routing` 字段完成状态流转：

```text
运营 -> 待运营修改
法务 -> 待法务复核
```

当前不建议随意修改 `/audit` 入参和响应字段，除非同步更新 `docs/interface_contract.md` 并与飞书状态机负责人确认。
