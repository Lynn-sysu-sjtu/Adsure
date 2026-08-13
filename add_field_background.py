"""
一次性脚本：在 v4 多维表格 ①运营段 新增「补充背景资料」文本字段

跑完后字段出现在表格里，运营填写时可以粘贴聊天中的背景信息。
⚠️ 此脚本只跑一次。
"""
import requests
from config import BITABLE_APP_TOKEN, BITABLE_TABLE_ID
from feishu_api import get_tenant_access_token

BASE = "https://open.feishu.cn/open-apis"
FT_TEXT = 1


def main():
    token = get_tenant_access_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 检查字段是否已存在
    r = requests.get(
        f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields",
        headers=h, params={"page_size": 100},
    ).json()
    existing = {f["field_name"] for f in r.get("data", {}).get("items", [])}

    field_name = "①运营·补充背景资料"
    if field_name in existing:
        print(f"✓ 字段「{field_name}」已存在，无需重复添加")
        return

    # 新增字段
    r = requests.post(
        f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields",
        headers=h,
        json={"field_name": field_name, "type": FT_TEXT},
    ).json()

    if r.get("code") == 0:
        fid = r["data"]["field"]["field_id"]
        print(f"✓ 字段「{field_name}」添加成功，field_id={fid}")
    else:
        print(f"✗ 添加失败 code={r.get('code')} msg={r.get('msg')}")


if __name__ == "__main__":
    main()
