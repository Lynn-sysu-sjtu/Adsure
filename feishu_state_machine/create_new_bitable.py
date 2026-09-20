"""
让应用自己创建一张全新的多维表格 + 35个字段

创建出来的表归应用所有，不需要任何额外授权。
跑完后会输出新表的URL，你打开URL就能看到完整的表。

运行: python3 create_new_bitable.py
"""
import requests
import time
from config import FEISHU_APP_ID, FEISHU_APP_SECRET

BASE_URL = "https://open.feishu.cn/open-apis"
NEW_BITABLE_NAME = "审心广告物料合规审核台 v2"

# ===== 字段类型常量 =====
FT_TEXT = 1
FT_NUMBER = 2
FT_SINGLE_SELECT = 3
FT_MULTI_SELECT = 4
FT_DATETIME = 5
FT_CHECKBOX = 7
FT_USER = 11
FT_ATTACHMENT = 17

# ===== 35个字段定义 =====
FIELDS = [
    {"field_name": "运营·物料编号", "type": FT_TEXT},
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
         {"name": "快手"}, {"name": "视频号"}, {"name": "今日头条"}, {"name": "其他"}]}},
    {"field_name": "运营·是否启用AI预审", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "是"}, {"name": "否"}]}},
    {"field_name": "运营·紧急程度", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "普通"}, {"name": "加急"}]}},
    {"field_name": "运营·提交人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "运营·提交时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
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
    return resp.json()["tenant_access_token"]


def main():
    print("【1】 获取 token...")
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"    OK: {token[:16]}...\n")

    # === 创建多维表格 app ===
    print(f"【2】 创建多维表格 「{NEW_BITABLE_NAME}」（应用所有）...")
    url = f"{BASE_URL}/bitable/v1/apps"
    resp = requests.post(url, headers=h, json={
        "name": NEW_BITABLE_NAME,
        # 不指定 folder_token，会创建在应用的根目录（应用云空间）
    })
    data = resp.json()
    print(f"    code={data.get('code')}, msg={data.get('msg')}")
    if data.get("code") != 0:
        print(f"    完整返回: {data}")
        print()
        print("可能原因:")
        print("  - 应用没开 docs:doc 或 drive:drive 权限（创建文档需要）")
        print("  - 应用没开 bitable:app 权限")
        return

    app_data = data["data"]["app"]
    new_app_token = app_data["app_token"]
    new_url = app_data.get("url", f"https://feishu.cn/base/{new_app_token}")
    print(f"    ✓ app_token = {new_app_token}")
    print(f"    ✓ URL = {new_url}\n")

    # === 找到默认表 ===
    print(f"【3】 列出默认表...")
    url = f"{BASE_URL}/bitable/v1/apps/{new_app_token}/tables"
    resp = requests.get(url, headers=h).json()
    if resp.get("code") != 0:
        print(f"    失败: {resp}")
        return
    tables = resp["data"]["items"]
    table_id = tables[0]["table_id"]
    print(f"    ✓ table_id = {table_id}\n")

    # === 找到主字段 ===
    print(f"【4】 读取主字段...")
    url = f"{BASE_URL}/bitable/v1/apps/{new_app_token}/tables/{table_id}/fields"
    resp = requests.get(url, headers=h).json()
    primary = resp["data"]["items"][0]
    print(f"    ✓ 主字段: id={primary['field_id']}, name={primary['field_name']}\n")

    # === 重命名主字段 ===
    print(f"【5】 重命名主字段为「{FIELDS[0]['field_name']}」...")
    url = f"{BASE_URL}/bitable/v1/apps/{new_app_token}/tables/{table_id}/fields/{primary['field_id']}"
    resp = requests.put(url, headers=h, json=FIELDS[0]).json()
    print(f"    code={resp.get('code')}, msg={resp.get('msg')}")
    time.sleep(0.3)

    # === 添加其他字段 ===
    print(f"\n【6】 添加剩余 {len(FIELDS)-1} 个字段...")
    url = f"{BASE_URL}/bitable/v1/apps/{new_app_token}/tables/{table_id}/fields"
    success = 0
    failed = []
    for i, fd in enumerate(FIELDS[1:], start=2):
        resp = requests.post(url, headers=h, json=fd).json()
        if resp.get("code") == 0:
            success += 1
            print(f"    [{i}/{len(FIELDS)}] ✓ {fd['field_name']}")
        else:
            failed.append((fd['field_name'], resp.get('msg')))
            print(f"    [{i}/{len(FIELDS)}] ✗ {fd['field_name']} → {resp.get('msg')}")
        time.sleep(0.3)

    print("\n" + "=" * 60)
    print(f"✅ 创建完成: 字段 {success + 1}/{len(FIELDS)}")
    if failed:
        print(f"⚠ 失败 {len(failed)} 个:")
        for name, msg in failed:
            print(f"   - {name}: {msg}")
    print()
    print("【新表信息】")
    print(f"  app_token: {new_app_token}")
    print(f"  table_id : {table_id}")
    print(f"  URL      : {new_url}")
    print()
    print("【下一步】")
    print(f"  1. 浏览器打开上面的 URL，确认表已建好")
    print(f"  2. 更新 config.py:")
    print(f'     BITABLE_APP_TOKEN = "{new_app_token}"')
    print(f'     BITABLE_TABLE_ID  = "{table_id}"')
    print("=" * 60)


if __name__ == "__main__":
    main()
