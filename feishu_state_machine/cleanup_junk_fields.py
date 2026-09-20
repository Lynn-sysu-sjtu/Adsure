"""
1. 删掉飞书默认带的旧字段（单选/日期/附件）
2. 试创建字段分组
"""
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE = "https://open.feishu.cn/open-apis"
JUNK_NAMES = {"单选", "日期", "附件"}


def get_token():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]


def list_all_fields(token):
    h = {"Authorization": f"Bearer {token}"}
    items, page_token = [], None
    while True:
        params = {"page_size": 100}
        if page_token: params["page_token"] = page_token
        r = requests.get(f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields",
                         headers=h, params=params).json()
        items.extend(r["data"]["items"])
        if not r["data"].get("has_more"): break
        page_token = r["data"].get("page_token")
    return items


def delete_field(token, fid, name):
    h = {"Authorization": f"Bearer {token}"}
    r = requests.delete(
        f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields/{fid}",
        headers=h).json()
    print(f"  删 {name} ({fid}): code={r.get('code')}, msg={r.get('msg')}")


def main():
    token = get_token()
    print("【1】 列字段...")
    fs = list_all_fields(token)
    print(f"    共 {len(fs)} 个字段")

    junks = [f for f in fs if f["field_name"] in JUNK_NAMES]
    print(f"\n【2】 发现 {len(junks)} 个垃圾字段，准备删除...")
    for f in junks:
        delete_field(token, f["field_id"], f["field_name"])

    print("\n【3】 重列字段确认...")
    fs2 = list_all_fields(token)
    print(f"    现在 {len(fs2)} 个字段")


if __name__ == "__main__":
    main()
