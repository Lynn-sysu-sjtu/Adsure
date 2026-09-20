"""
试探飞书 字段分组(field_group) API 是否可用
猜测的端点: POST /bitable/v1/apps/{app_token}/tables/{table_id}/field_groups
"""
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE = "https://open.feishu.cn/open-apis"


def get_token():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]


def try_endpoint(method, path, body=None, params=None):
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{BASE}{path}"
    print(f"\n>>> {method} {path}")
    if body: print(f"    body={body}")
    r = requests.request(method, url, headers=h, json=body, params=params)
    try:
        data = r.json()
        print(f"    HTTP {r.status_code}, code={data.get('code')}, msg={data.get('msg')}")
        if data.get("code") != 0:
            print(f"    完整: {data}")
        else:
            print(f"    OK data={data.get('data')}")
        return data
    except Exception:
        print(f"    HTTP {r.status_code}, raw={r.text[:300]}")
        return None


# 1. 列出字段分组
try_endpoint("GET", f"/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/field_groups")

# 2. 试创建一个分组
try_endpoint("POST",
             f"/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/field_groups",
             body={"name": "①运营提交区"})

# 3. 试 list fields 看是否带分组信息
try_endpoint("GET",
             f"/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields",
             params={"page_size": 5})
