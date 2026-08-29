# 复制此文件为 config.py，填入真实值后运行
# cp config.example.py config.py

# 队友规则引擎配置
RULE_ENGINE_URL     = "http://your-engine-host"   # 不含路径，调用时拼 /audit
RULE_ENGINE_API_KEY = "your_rule_engine_api_key"

# 案例库配置（另一位队友提供）
CASE_ENGINE_URL     = "http://your-case-engine-host"   # 不含路径，调用时拼 /cases/retrieve
CASE_ENGINE_API_KEY = "your_case_engine_api_key"

# LLM API 配置（Anthropic 格式，支持中转站）
LLM_API_KEY  = "your_llm_api_key"
LLM_BASE_URL = "https://api.anthropic.com"   # 或中转站地址
LLM_MODEL    = "claude-opus-4-7"             # 或 deepseek-v4-pro 等

# 法务工作台公网地址（本地开发用 localhost:5001）
WORKBENCH_URL   = "http://localhost:5001"
LEGAL_DEPT_NAME = "法律与合规"       # 飞书组织架构中法务部门名称
OPS_DEPT_NAME   = "运营与市场营销"   # 飞书组织架构中运营部门名称（备用）
LEGAL_OPEN_IDS  = []                 # 组织架构查询不可用时的法务 open_id 兜底

# 飞书开放平台 — 企业自建应用
FEISHU_APP_ID     = "cli_xxxx"
FEISHU_APP_SECRET = "your_feishu_app_secret"

# 飞书多维表格
BITABLE_APP_TOKEN = "your_bitable_app_token"
BITABLE_TABLE_ID  = "your_bitable_table_id"

# 可靠任务与投递（SQLite；目录需可持久化，不能放临时目录）
ADSURE_DB_PATH                = "data/adsure_jobs.sqlite3"
ADSURE_DB_BUSY_TIMEOUT_MS     = 5000
ADSURE_JOB_LEASE_SECONDS      = 120
ADSURE_JOB_MAX_ATTEMPTS       = 5
ADSURE_DELIVERY_MAX_ATTEMPTS  = 5
ADSURE_RETRY_BASE_SECONDS     = 2
ADSURE_RETRY_MAX_SECONDS      = 60

# HTTP 卡片回调校验
# 兼容迁移期默认关闭；填好飞书后台的 Verification Token / Encrypt Key 后再开启。
FEISHU_CALLBACK_VERIFY_ENABLED = False
FEISHU_VERIFICATION_TOKEN      = ""
FEISHU_ENCRYPT_KEY             = ""
FEISHU_CALLBACK_MAX_AGE_SECONDS = 300

# 默认关闭调试页；仅本机开发时显式改为 True
FLASK_DEBUG = False

# 可选：腾讯云图片文字识别；留空时文字物料仍可正常审核
TENCENT_SECRET_ID  = ""
TENCENT_SECRET_KEY = ""
TENCENT_OCR_REGION = "ap-guangzhou"

# 字段ID映射（一般无需修改，字段名即为飞书字段名）
FIELD_MAP = {
    "物料内容": "物料内容",
    "行业领域": "行业领域",
    "风险等级": "风险等级",
    "违规类型": "违规类型",
    "AI审核意见": "AI审核意见",
    "AI抽取-高风险词命中": "AI抽取-高风险词命中",
    "AI抽取-备案核查结果": "AI抽取-备案核查结果",
    "审核状态": "审核状态",
    "AI意见评价": "AI意见评价",
    "物料裁决": "物料裁决",
    "异议字段": "异议字段",
    "法务补充或驳回理由": "法务补充或驳回理由",
    "驳回正确判定": "驳回正确判定",
    "最终修改意见": "最终修改意见",
    "法务批注": "法务批注",
    "反馈类型": "反馈类型",
    "提交人": "提交人",
    "提交时间": "提交时间",
}
