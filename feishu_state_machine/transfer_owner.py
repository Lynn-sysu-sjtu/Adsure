"""
通过邮箱或手机号查飞书 open_id，并把多维表格的所有者转让给该用户

用途：应用通过API创建的多维表格归应用所有，需要把所有权转让给真人用户

使用：
  1. 在 USER_EMAIL 或 USER_MOBILE 填入你的飞书账号信息
  2. python3 transfer_owner.py
"""
import requests
from config import (
    FEISHU_APP_ID, FEISHU_APP_SECRET,
    BITABLE_APP_TOKEN
)

BASE_URL = "https://open.feishu.cn/open-apis"

# ===== 在这里填入你的飞书账号信息（任选一个）=====
USER_EMAIL = ""    # 例如 "you@example.com"
USER_MOBILE = "13395778231"   # 例如 "13800000000"，国内手机号不要+86


def get_token():
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return resp.json()["tenant_access_token"]


def query_user_id(token):
    """通过邮箱/手机号反查 user_id 和 open_id"""
    url = f"{BASE_URL}/contact/v3/users/batch_get_id"
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {}
    if USER_EMAIL:
        body["emails"] = [USER_EMAIL]
    if USER_MOBILE:
        body["mobiles"] = [USER_MOBILE]
    if not body:
        raise Exception("请在脚本里填 USER_EMAIL 或 USER_MOBILE")
    body["include_resigned"] = False
    resp = requests.post(url + "?user_id_type=open_id", headers=h, json=body)
    return resp.json()


def transfer_owner(token, member_id, member_type="openid"):
    """转让多维表格所有者
    perm: 1=可阅读 2=可编辑 4=可管理 (所有者通过额外字段)
    """
    url = f"{BASE_URL}/drive/v1/permissions/{BITABLE_APP_TOKEN}/members/transfer_owner"
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"type": "bitable", "need_notification": "true"}
    body = {
        "member_type": member_type,  # openid / userid / email / openchat / department
        "member_id": member_id,
        "old_owner_perm": "full_access",  # 把旧owner降级为全部权限
    }
    resp = requests.post(url, headers=h, params=params, json=body)
    return resp.json()


def main():
    print("【1】 获取 token...")
    token = get_token()
    print(f"    OK\n")

    print("【2】 查询你的 open_id...")
    res = query_user_id(token)
    print(f"    返回: code={res.get('code')}, msg={res.get('msg')}")
    if res.get("code") != 0:
        print(f"    完整: {res}")
        print("\n可能原因: 应用没开 contact:user.id:readonly 或类似权限")
        return

    users = res.get("data", {}).get("user_list", [])
    if not users or not users[0].get("user_id"):
        print(f"    ❌ 未找到该用户。完整返回: {res}")
        return
    user = users[0]
    open_id = user.get("user_id")
    print(f"    ✓ open_id = {open_id}\n")

    print(f"【3】 转让多维表格所有者给 {open_id}...")
    res = transfer_owner(token, open_id, "openid")
    print(f"    返回: code={res.get('code')}, msg={res.get('msg')}")
    if res.get("code") == 0:
        print(f"    ✅ 转让成功！现在你是这张表的所有者，应用降级为可编辑")
        print(f"    打开看看: https://dcnhexeh6nru.feishu.cn/base/{BITABLE_APP_TOKEN}")
    else:
        print(f"    ❌ 失败完整: {res}")


if __name__ == "__main__":
    main()
