"""
诊断脚本：查询法务部门成员的 open_id
运行：python3 get_legal_open_ids.py
"""
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, LEGAL_DEPT_NAME

BASE_URL = "https://open.feishu.cn/open-apis"


def get_token():
    r = requests.post(f"{BASE_URL}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]


def list_children(token, parent_id):
    items = []
    page_token = None
    while True:
        params = {
            "user_id_type": "open_id",
            "department_id_type": "open_department_id",
            "parent_department_id": parent_id,
            "page_size": 50,
        }
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{BASE_URL}/contact/v3/departments",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        ).json()
        code = resp.get("code")
        if code != 0:
            print(f"  [!] 列出子部门失败 parent={parent_id}: code={code} msg={resp.get('msg')}")
            break
        items.extend(resp.get("data", {}).get("items", []))
        if not resp.get("data", {}).get("has_more"):
            break
        page_token = resp.get("data", {}).get("page_token")
    return items


def main():
    token = get_token()
    print(f"Token OK\n")

    # BFS 打印整棵部门树
    print("【部门树】")
    queue = [("0", 0)]
    dept_id = None
    while queue:
        parent_id, depth = queue.pop(0)
        children = list_children(token, parent_id)
        for dept in children:
            name = dept.get("name")
            did  = dept.get("open_department_id")
            print(f"{'  ' * depth}├─ {name}  (id={did})")
            if name == LEGAL_DEPT_NAME:
                dept_id = did
                print(f"{'  ' * depth}   *** 匹配！***")
            queue.append((did, depth + 1))

    print()
    if not dept_id:
        print(f"[!] 未找到部门「{LEGAL_DEPT_NAME}」，请检查 config.py 中 LEGAL_DEPT_NAME 是否与飞书中完全一致")
        return

    # 拉取成员
    print(f"【「{LEGAL_DEPT_NAME}」成员列表】")
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
        resp = requests.get(
            f"{BASE_URL}/contact/v3/users",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        ).json()
        if resp.get("code") != 0:
            print(f"[!] 获取成员失败: code={resp.get('code')} msg={resp.get('msg')}")
            break
        for u in resp.get("data", {}).get("items", []):
            name  = u.get("name", "?")
            oid   = u.get("open_id", "?")
            open_ids.append(oid)
            print(f"  {name}  →  {oid}")
        if not resp.get("data", {}).get("has_more"):
            break
        page_token = resp.get("data", {}).get("page_token")

    print()
    if open_ids:
        print("【复制以下内容到 config.py 的 LEGAL_OPEN_IDS 】")
        print("LEGAL_OPEN_IDS = [")
        for oid in open_ids:
            print(f'    "{oid}",')
        print("]")
    else:
        print(f"[!] 部门「{LEGAL_DEPT_NAME}」下没有成员（或无权限读取）")


if __name__ == "__main__":
    main()
