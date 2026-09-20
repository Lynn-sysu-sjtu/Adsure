"""
按段（①②③④⑤）创建字段分组（最终版）

格式: children = [{"id": field_id, "type": "field"}, ...]
"""
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE = "https://open.feishu.cn/open-apis"

GROUPS = [
    ("①", "①运营提交区"),
    ("②", "②AI预审区"),
    ("③", "③AI审核区"),
    ("④", "④法务裁决区"),
    ("⑤", "⑤流转沉淀区"),
]


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


def list_field_groups(token):
    """看下已有哪些分组（试探接口形态）"""
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/field_groups",
                     headers=h)
    print(f"  list groups: HTTP {r.status_code} {r.text[:300]}")


def main():
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print("【1】 列字段...")
    fields = list_all_fields(token)
    print(f"    共 {len(fields)} 个\n")

    # 按段聚类（主字段不能进分组）
    buckets = {prefix: [] for prefix, _ in GROUPS}
    for f in fields:
        if f.get("is_primary"):
            continue
        for prefix, _ in GROUPS:
            if f["field_name"].startswith(prefix):
                buckets[prefix].append(f["field_id"])
                break

    payload = []
    print("【2】 准备分组：")
    for prefix, name in GROUPS:
        ids = buckets[prefix]
        print(f"    {name}: {len(ids)} 个字段")
        if ids:
            payload.append({
                "name": name,
                "children": [{"id": fid, "type": "field"} for fid in ids],
            })

    print(f"\n【3】 调用 API 创建 {len(payload)} 个分组...")
    url = f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/field_groups"
    r = requests.post(url, headers=h, json={"field_groups": payload}).json()
    print(f"    code={r.get('code')}, msg={r.get('msg')}")
    if r.get("code") == 0:
        print(f"    ✓ 成功!")
        data = r.get("data", {})
        for g in data.get("field_groups", []):
            print(f"      - {g.get('name')} (id={g.get('field_group_id')})")
    else:
        print(f"    完整: {r}")


if __name__ == "__main__":
    main()
