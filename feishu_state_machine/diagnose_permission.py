"""
权限诊断 — 找出哪些操作能做、哪些不能
"""
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE_URL = "https://open.feishu.cn/open-apis"


def get_token():
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return resp.json()["tenant_access_token"]


def main():
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print("=== 权限诊断 ===\n")

    # 1. 读 bitable 元信息
    print("[1] 读取 bitable 应用信息")
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}"
    resp = requests.get(url, headers=h).json()
    print(f"    code={resp.get('code')}, msg={resp.get('msg')}")
    if resp.get("code") == 0:
        app_info = resp.get("data", {}).get("app", {})
        print(f"    ✓ 应用名: {app_info.get('name')}")
        print(f"    ✓ 是否高级权限: {app_info.get('is_advanced')}")

    # 2. 列字段
    print("\n[2] 列字段（读）")
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields"
    resp = requests.get(url, headers=h).json()
    print(f"    code={resp.get('code')}, msg={resp.get('msg')}")
    if resp.get("code") == 0:
        print(f"    ✓ 现有 {len(resp['data']['items'])} 个字段")

    # 3. 尝试新建一个最简单的字段
    print("\n[3] 尝试新建一个测试字段（写）")
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields"
    resp = requests.post(url, headers=h, json={
        "field_name": "_诊断测试_可删除",
        "type": 1
    }).json()
    print(f"    code={resp.get('code')}, msg={resp.get('msg')}")
    if resp.get("code") == 0:
        print(f"    ✓ 写权限正常！")
        # 删掉测试字段
        fid = resp["data"]["field"]["field_id"]
        del_url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields/{fid}"
        requests.delete(del_url, headers=h)
        print(f"    ✓ 已清理测试字段")
    else:
        print(f"    ✗ 写权限不足")

    print("\n=== 诊断结论 ===")
    print("如果 [2] 成功但 [3] 失败 → 应用对该wiki空间没有「可编辑」权限")
    print("解决: 进入wiki空间 → 设置 → 成员/协作者 → 把应用权限改为「可编辑」")
    print()
    print("如果 [3] 报权限相关错误 → 检查飞书开发者后台是否有 bitable:app（写）权限")
    print("注意: bitable:app:readonly 是只读，必须额外开 bitable:app")


if __name__ == "__main__":
    main()
