"""
试探脚本 — 在执行完整建表前，先验证以下几点：
1. 当前token权限是否够创建数据表（需要 bitable:app 权限）
2. 飞书API对各种字段类型的支持是否正常
3. 字段属性（property）的格式是否正确

成功后会创建一个测试表，包含3个代表性字段。
确认无问题后，去飞书把这个测试表删掉，再跑完整版 setup_bitable_v2.py
"""
import requests
import time
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN

BASE_URL = "https://open.feishu.cn/open-apis"
TEST_TABLE_NAME = "_API测试表_可删除"


def get_token():
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取token失败: {data}")
    return data["tenant_access_token"]


def main():
    print("【1】 获取 token...")
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"    OK: {token[:16]}...\n")

    # === 测试1：能否新建数据表 ===
    print("【2】 测试新建数据表...")
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables"
    resp = requests.post(url, headers=h,
        json={"table": {"name": TEST_TABLE_NAME, "default_view_name": "全部"}})
    data = resp.json()
    print(f"    返回: code={data.get('code')}, msg={data.get('msg')}")
    if data.get("code") != 0:
        print(f"    ❌ 失败: {data}")
        print("    可能原因: 应用权限不足，需要在飞书开发者后台开启「bitable:app」权限")
        return
    table_id = data["data"]["table_id"]
    print(f"    ✓ table_id = {table_id}\n")

    # === 测试2：读取默认主字段 ===
    print("【3】 读取默认主字段...")
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/fields"
    resp = requests.get(url, headers=h)
    data = resp.json()
    if data.get("code") != 0:
        print(f"    ❌ 失败: {data}")
        return
    fields = data["data"]["items"]
    primary = fields[0]
    print(f"    ✓ 默认字段: id={primary['field_id']}, name={primary['field_name']}, type={primary.get('type')}\n")

    # === 测试3：重命名主字段（文本类型） ===
    print("【4】 测试 重命名主字段为 文本类型...")
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/fields/{primary['field_id']}"
    resp = requests.put(url, headers=h, json={"field_name": "测试·物料编号", "type": 1})
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")
    time.sleep(0.3)

    # === 测试4：单选字段（带选项+颜色） ===
    print("\n【5】 测试 单选字段（带颜色选项）...")
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{table_id}/fields"
    resp = requests.post(url, headers=h, json={
        "field_name": "测试·风险等级",
        "type": 3,
        "property": {"options": [
            {"name": "高", "color": 0},
            {"name": "中", "color": 1},
            {"name": "低", "color": 2},
        ]}
    })
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")
    time.sleep(0.3)

    # === 测试5：多选字段 ===
    print("\n【6】 测试 多选字段...")
    resp = requests.post(url, headers=h, json={
        "field_name": "测试·投放平台",
        "type": 4,
        "property": {"options": [
            {"name": "抖音"}, {"name": "小红书"}, {"name": "微信"},
        ]}
    })
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")
    time.sleep(0.3)

    # === 测试6：日期时间字段 ===
    print("\n【7】 测试 日期时间字段...")
    resp = requests.post(url, headers=h, json={
        "field_name": "测试·时间",
        "type": 5,
        "property": {"date_formatter": "yyyy/MM/dd HH:mm"}
    })
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")
    time.sleep(0.3)

    # === 测试7：人员字段 ===
    print("\n【8】 测试 人员字段...")
    resp = requests.post(url, headers=h, json={
        "field_name": "测试·人员",
        "type": 11,
        "property": {"multiple": False}
    })
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")
    time.sleep(0.3)

    # === 测试8：附件字段 ===
    print("\n【9】 测试 附件字段...")
    resp = requests.post(url, headers=h, json={"field_name": "测试·附件", "type": 17})
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")
    time.sleep(0.3)

    # === 测试9：复选框 ===
    print("\n【10】 测试 复选框字段...")
    resp = requests.post(url, headers=h, json={"field_name": "测试·复选框", "type": 7})
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")
    time.sleep(0.3)

    # === 测试10：数字字段 ===
    print("\n【11】 测试 数字字段...")
    resp = requests.post(url, headers=h, json={
        "field_name": "测试·数字", "type": 2,
        "property": {"formatter": "0"}
    })
    print(f"    返回: code={resp.json().get('code')}, msg={resp.json().get('msg')}")

    print("\n" + "=" * 60)
    print(f"✅ 测试完成")
    print(f"   测试表: {TEST_TABLE_NAME}")
    print(f"   table_id: {table_id}")
    print()
    print("请去飞书多维表格里查看：")
    print("  - 字段类型是否都正确")
    print("  - 单选/多选的选项是否正常")
    print()
    print("确认无误后：")
    print("  1. 在飞书里手动删除这个测试表")
    print("  2. 跑 python3 setup_bitable_v2.py 创建正式表")
    print("=" * 60)


if __name__ == "__main__":
    main()
