# 队友规则引擎配置（待队友提供后填入）
RULE_ENGINE_URL     = "http://124.223.111.170:8504/audit"
RULE_ENGINE_API_KEY = "adsure_sk_cloud_Zn18HtG-UsPmPoLXPVVIIIszasXTf5PB"

# LLM API 配置（Anthropic 格式中转站）
LLM_API_KEY  = "sk-243f3fcd43154f248240e354712a0316"
LLM_BASE_URL = "https://www.right.codes/deepseek/anthropic"
LLM_MODEL    = "deepseek-v4-pro"

# 法务工作台配置
WORKBENCH_URL    = "http://localhost:5001"   # 上线后换成公网地址
LEGAL_DEPT_NAME  = "法律与合规"              # 飞书组织架构里法务部门的名称
OPS_DEPT_NAME    = "运营与市场营销"          # 飞书组织架构里运营部门的名称（暂未使用，备用）

# 飞书开放平台配置
# 在飞书开发者后台创建企业自建应用后填入真实值

FEISHU_APP_ID = "cli_aaa33f1e7b389be5"
FEISHU_APP_SECRET = "1qaFhT6txgmdMbc1KA6YZg3Wa3wdx21u"

# 多维表格信息（v4 — 5段分组 + 美妆/游戏/保健食品 行业专属字段，A方案配套）
# URL: https://dcnhexeh6nru.feishu.cn/base/Jp48bY4Q2aGvc8sZouHcWqnFnpb
# 表名: 审心广告物料合规审核台 v4
BITABLE_APP_TOKEN = "Jp48bY4Q2aGvc8sZouHcWqnFnpb"
BITABLE_TABLE_ID = "tblL8R7yL1rCeU7m"

# 弃用记录:
# v1 旧表（飞书企业号下的旧多维表格）
# BITABLE_APP_TOKEN = "SuRKb33DlaelvDsx1K0cAlB3nBh"
# BITABLE_TABLE_ID  = "tbl1NS2cEBnc5G7q"
# v2 wiki版（授权问题已弃用）
# BITABLE_APP_TOKEN = "KptFbbaD7a93mxscXsXc0AYfn1g"
# BITABLE_TABLE_ID  = "tblzaR1H6TRCfMri"
# v2 用户手建独立表（写权限被拒已弃用）
# BITABLE_APP_TOKEN = "WXn0blhWza0KwZs6KgTc0ruHn4e"
# BITABLE_TABLE_ID  = "tbl9SP3ATJrKvUos"
# v2 通用35字段（设计偏离A方案已废弃）
# BITABLE_APP_TOKEN = "T9oObYahqap6aYsKsQqc4eIfnCe"
# BITABLE_TABLE_ID  = "tblfDDfZwKe0HJhd"
# v3 调试时误建测试分组占用字段已废弃
# BITABLE_APP_TOKEN = "GpDLbQMlVaRaKjsnKsjcrmKLntg"
# BITABLE_TABLE_ID  = "tblLK62JO9ohBoes"

# 字段ID映射（需要从飞书API获取真实字段ID，暂时用字段名占位）
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
