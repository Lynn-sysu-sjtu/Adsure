"""
通过飞书开放平台 API 自动创建 v2 多维表格数据表
- 在现有多维表格应用下新建数据表
- 自动建好35个字段，配置好类型（单选/多选/日期/人员/附件等）
- 单选/多选字段一并填好选项值

运行: python3 setup_bitable_v2.py
"""
import requests
import json
import time
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN

BASE_URL = "https://open.feishu.cn/open-apis"

# 数据表名（如有重名飞书会拒绝创建）
NEW_TABLE_NAME = "物料合规审核 v2"


# ===== 飞书字段 type 常量 =====
# 完整列表见 https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-field/guide
FT_TEXT = 1          # 多行文本
FT_NUMBER = 2        # 数字
FT_SINGLE_SELECT = 3 # 单选
FT_MULTI_SELECT = 4  # 多选
FT_DATETIME = 5      # 日期时间
FT_CHECKBOX = 7      # 复选框
FT_USER = 11         # 人员
FT_ATTACHMENT = 17   # 附件
FT_AUTONUM = 1005    # 自动编号
FT_CREATED_TIME = 1001 # 创建时间
FT_CREATED_USER = 1003 # 创建人


# ===== 字段定义 =====
# 注意：飞书要求第一个字段（主字段/索引字段）必须是文本类型
FIELDS = [
    # ① 运营提交
    {"field_name": "运营·物料编号", "type": FT_TEXT},  # 主字段必须文本
    {"field_name": "运营·物料内容", "type": FT_TEXT},
    {"field_name": "运营·物料附件", "type": FT_ATTACHMENT},
    {"field_name": "运营·行业领域", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "美妆"}, {"name": "游戏"}, {"name": "影音"}]}},
    {"field_name": "运营·物料类型", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
         {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "运营·投放平台", "type": FT_MULTI_SELECT,
     "property": {"options": [
         {"name": "抖音"}, {"name": "小红书"}, {"name": "微信"},
         {"name": "B站"}, {"name": "淘宝"}, {"name": "微博"},
         {"name": "快手"}, {"name": "视频号"}, {"name": "今日头条"},
         {"name": "其他"}]}},
    {"field_name": "运营·是否启用AI预审", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "是"}, {"name": "否"}]}},
    {"field_name": "运营·紧急程度", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "普通"}, {"name": "加急"}]}},
    {"field_name": "运营·提交人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "运营·提交时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},

    # ② AI预审段
    {"field_name": "AI预审·风险等级", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "高", "color": 0}, {"name": "中", "color": 1},
         {"name": "低", "color": 2}, {"name": "无明显风险", "color": 3}]}},
    {"field_name": "AI预审·命中要点", "type": FT_TEXT},
    {"field_name": "AI预审·修改建议", "type": FT_TEXT},
    {"field_name": "AI预审·时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "AI预审·运营修改记录", "type": FT_TEXT},
    {"field_name": "AI预审·运营是否采纳建议", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "全部采纳"}, {"name": "部分采纳"},
         {"name": "未采纳"}, {"name": "未使用预审"}]}},

    # ③ AI审核段
    {"field_name": "AI审核·审核意见", "type": FT_TEXT},
    {"field_name": "AI审核·高风险词命中", "type": FT_TEXT},
    {"field_name": "AI审核·备案核查结果", "type": FT_TEXT},
    {"field_name": "AI审核·推荐违规类型", "type": FT_MULTI_SELECT,
     "property": {"options": [
         {"name": "绝对化用语"}, {"name": "虚假宣传"},
         {"name": "功效超出备案"}, {"name": "医疗用语"},
         {"name": "数据引用不规范"}, {"name": "概率未公示"},
         {"name": "未成年人保护"}, {"name": "版号缺失"},
         {"name": "AIGC未标识"}, {"name": "许可证缺失"},
         {"name": "广告不可识别"}, {"name": "等价广告违规"},
         {"name": "含恐怖暴力内容"}, {"name": "其他"}]}},
    {"field_name": "AI审核·推荐风险等级", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "高", "color": 0}, {"name": "中", "color": 1}, {"name": "低", "color": 2}]}},
    {"field_name": "AI审核·审核时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},

    # ④ 法务裁决段
    {"field_name": "法务·AI意见评价", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "同意无补充"}, {"name": "同意有补充"}, {"name": "驳回"}]}},
    {"field_name": "法务·物料裁决", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "通过"}, {"name": "不通过"}]}},
    {"field_name": "法务·异议字段", "type": FT_MULTI_SELECT,
     "property": {"options": [
         {"name": "风险等级"}, {"name": "违规类型"},
         {"name": "高风险词识别"}, {"name": "备案核查"}, {"name": "其他"}]}},
    {"field_name": "法务·补充或驳回理由", "type": FT_TEXT},
    {"field_name": "法务·驳回正确判定", "type": FT_TEXT},
    {"field_name": "法务·最终修改意见", "type": FT_TEXT},
    {"field_name": "法务·批注", "type": FT_TEXT},
    {"field_name": "法务·复核人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "法务·复核时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},

    # ⑤ 流转沉淀段
    {"field_name": "流转·当前状态", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "运营起草"}, {"name": "AI预审中"},
         {"name": "运营修改中"}, {"name": "待法务复核"},
         {"name": "已通过"}, {"name": "需修改"},
         {"name": "已上线"}, {"name": "已撤回"}]}},
    {"field_name": "流转·反馈类型", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "refine"}, {"name": "override"}, {"name": "无"}]}},
    {"field_name": "流转·是否进入大脑沉淀", "type": FT_CHECKBOX},
    {"field_name": "流转·轮次", "type": FT_NUMBER, "property": {"formatter": "0"}},
]


def get_token():
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取token失败: {data}")
    return data["tenant_access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_table(token, table_name):
    """新建一个数据表"""
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables"
    body = {"table": {"name": table_name, "default_view_name": "全部记录"}}
    resp = requests.post(url, headers=headers(token), json=body)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"建表失败: {data}")
    table_id = data["data"]["table_id"]
    return table_id


def list_fields(token, table_id):
    """读取表里现有的字段（建表会自带一个默认主字段）"""
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/fields"
    resp = requests.get(url, headers=headers(token))
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"读取字段失败: {data}")
    return data["data"]["items"]


def update_field(token, table_id, field_id, field_def):
    """更新（重命名/改类型）字段"""
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/fields/{field_id}"
    resp = requests.put(url, headers=headers(token), json=field_def)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"更新字段失败 {field_def['field_name']}: {data}")
    return data


def create_field(token, table_id, field_def):
    """在表里新建字段"""
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/fields"
    resp = requests.post(url, headers=headers(token), json=field_def)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"建字段失败 {field_def['field_name']}: {data}")
    return data


def main():
    print("【1/4】 获取 access token...")
    token = get_token()
    print(f"     token OK: {token[:16]}...")

    print(f"\n【2/4】 创建数据表「{NEW_TABLE_NAME}」...")
    table_id = create_table(token, NEW_TABLE_NAME)
    print(f"     table_id = {table_id}")

    print("\n【3/4】 读取默认主字段...")
    existing = list_fields(token, table_id)
    primary = existing[0]
    print(f"     默认主字段 id={primary['field_id']}, name={primary['field_name']}")

    print(f"\n【4/4】 配置 {len(FIELDS)} 个字段...")
    # 第1个字段：把默认主字段重命名为「运营·物料编号」
    first = FIELDS[0]
    print(f"     [1/{len(FIELDS)}] 重命名主字段为「{first['field_name']}」")
    update_field(token, table_id, primary["field_id"], first)
    time.sleep(0.3)

    # 后续字段：逐个新建
    for i, fd in enumerate(FIELDS[1:], start=2):
        print(f"     [{i}/{len(FIELDS)}] 新建「{fd['field_name']}」 ({fd['type']})")
        try:
            create_field(token, table_id, fd)
        except Exception as e:
            print(f"          ⚠ {e}")
        time.sleep(0.3)  # 避免触发频率限制

    print("\n" + "=" * 60)
    print("✅ 建表完成")
    print(f"   表名: {NEW_TABLE_NAME}")
    print(f"   table_id: {table_id}")
    print(f"   字段数: {len(FIELDS)}")
    print("\n下一步：")
    print(f"  1. 打开飞书多维表格，会看到新增的「{NEW_TABLE_NAME}」数据表")
    print(f"  2. 检查字段类型是否正确")
    print(f"  3. 把这个 table_id 更新到 config.py 的 BITABLE_TABLE_ID")
    print(f"     新值: BITABLE_TABLE_ID = \"{table_id}\"")
    print("=" * 60)


if __name__ == "__main__":
    main()
