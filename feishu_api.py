"""
飞书开放平台 API 封装 — 多维表格读写
"""
import time
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE_URL = "https://open.feishu.cn/open-apis"

# 缓存 token，避免频繁请求
_token_cache = {"token": None, "expire": 0}


def get_tenant_access_token():
    """获取 tenant_access_token（应用身份令牌）"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expire"]:
        return _token_cache["token"]

    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    })
    data = resp.json()

    if data.get("code") != 0:
        raise Exception(f"获取token失败: {data.get('msg', data)}")

    token = data["tenant_access_token"]
    expire = data.get("expire", 7200)
    _token_cache["token"] = token
    _token_cache["expire"] = now + expire - 300  # 提前5分钟刷新
    return token


def _headers():
    """构建请求头"""
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json",
    }


def list_records(filter_formula=None, page_size=100, page_token=None):
    """
    读取多维表格记录
    filter_formula: 筛选公式，如 CurrentValue.[审核状态]="待人工复核"
    """
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"

    params = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token

    body = {}
    if filter_formula:
        body["filter"] = filter_formula

    # 用 GET + query params（飞书bitable list接口）
    resp = requests.get(url, headers=_headers(), params=params)
    data = resp.json()

    if data.get("code") != 0:
        raise Exception(f"读取记录失败: code={data.get('code')}, msg={data.get('msg', data)}")

    items = data.get("data", {}).get("items", [])
    has_more = data.get("data", {}).get("has_more", False)
    next_token = data.get("data", {}).get("page_token", None)

    return items, has_more, next_token


def list_all_records(filter_formula=None):
    """读取所有记录（自动翻页）"""
    all_items = []
    page_token = None

    while True:
        items, has_more, page_token = list_records(
            filter_formula=filter_formula,
            page_token=page_token
        )
        all_items.extend(items)
        if not has_more:
            break

    return all_items


def get_record(record_id):
    """读取单条记录"""
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/{record_id}"
    resp = requests.get(url, headers=_headers())
    data = resp.json()

    if data.get("code") != 0:
        raise Exception(f"读取记录失败: {data.get('msg', data)}")

    return data.get("data", {}).get("record", {})


def update_record(record_id, fields):
    """
    更新多维表格记录
    record_id: 记录ID
    fields: 要更新的字段字典，如 {"审核状态": "已通过", "物料裁决": "通过"}
    """
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/{record_id}"
    body = {"fields": fields}

    resp = requests.put(url, headers=_headers(), json=body)
    data = resp.json()

    if data.get("code") != 0:
        raise Exception(f"更新记录失败: {data.get('msg', data)}")

    return data.get("data", {}).get("record", {})


def search_records(filter_formula, page_size=100):
    """
    使用 search 接口筛选记录（支持复杂筛选条件）
    filter_formula 示例: 'AND(CurrentValue.[审核状态]="待人工复核")'
    """
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records/search"

    body = {
        "page_size": page_size,
        "filter": {
            "conjunction": "and",
            "conditions": []
        }
    }

    # 简单场景：直接用 list_records
    # search 接口用于更复杂的筛选需求，暂不使用
    pass


# === 组织架构：按部门名称查成员 ===

_dept_cache: dict = {}   # {dept_name: [open_id, ...]}，缓存 10 分钟


def get_dept_open_ids(dept_name: str) -> list:
    """
    按部门名称返回该部门所有成员的 open_id 列表。
    需要应用已开通权限：contact:contact.base:readonly
    实现：从根部门 BFS 遍历子部门树，按名称匹配，避免 /search 路径被误识别为 department_id。
    """
    import time
    cache_key = dept_name
    cached = _dept_cache.get(cache_key)
    if cached and time.time() < cached["expire"]:
        return cached["ids"]

    token = get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 第一步：列出所有部门，按名称匹配（/children 接口权限受限，改用 list 接口）
    dept_id = None
    page_token = None
    while True:
        params = {
            "user_id_type": "open_id",
            "department_id_type": "open_department_id",
            "page_size": 50,
        }
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{BASE_URL}/contact/v3/departments",
            headers=headers,
            params=params,
        ).json()
        if resp.get("code") != 0:
            print(f"[feishu_api] 列出部门失败: {resp.get('msg')} (code={resp.get('code')})")
            break
        for dept in resp.get("data", {}).get("items", []):
            if dept.get("name") == dept_name:
                dept_id = dept.get("open_department_id")
                break
        if dept_id or not resp.get("data", {}).get("has_more"):
            break
        page_token = resp.get("data", {}).get("page_token")
    if not dept_id:
        print(f"[feishu_api] 未找到部门「{dept_name}」")
        return []

    # 第二步：拉取该部门成员
    open_ids = []
    page_token = None
    while True:
        params = {
            "user_id_type": "open_id",
            "department_id_type": "open_department_id",
            "department_id": dept_id,
            "page_size": 50,
        }
        if page_token:
            params["page_token"] = page_token
        members_resp = requests.get(
            f"{BASE_URL}/contact/v3/users",
            headers=headers,
            params=params,
        ).json()
        if members_resp.get("code") != 0:
            raise Exception(f"获取部门成员失败: {members_resp.get('msg')} (code={members_resp.get('code')})")
        for u in members_resp.get("data", {}).get("items", []):
            oid = u.get("open_id")
            if oid:
                open_ids.append(oid)
        if not members_resp.get("data", {}).get("has_more"):
            break
        page_token = members_resp.get("data", {}).get("page_token")

    _dept_cache[cache_key] = {"ids": open_ids, "expire": time.time() + 600}
    print(f"[feishu_api] 部门「{dept_name}」查到 {len(open_ids)} 名成员")
    return open_ids


# === 测试连接 ===
if __name__ == "__main__":
    print("正在测试飞书API连接...")
    try:
        token = get_tenant_access_token()
        print(f"Token获取成功: {token[:20]}...")

        print("\n正在读取多维表格记录...")
        records, has_more, _ = list_records()
        print(f"共获取 {len(records)} 条记录")

        if records:
            print("\n第一条记录的字段名：")
            first = records[0]
            print(f"  record_id: {first.get('record_id')}")
            fields = first.get("fields", {})
            for key in sorted(fields.keys()):
                val = fields[key]
                preview = str(val)[:60]
                print(f"  {key}: {preview}")
    except Exception as e:
        print(f"错误: {e}")
