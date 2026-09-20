"""
一次性脚本：给「①游戏·投放平台」字段追加缺失的「小红书」选项。
运行方式：python3 add_game_platform_options.py
"""
import sys, requests
from feishu_api import get_tenant_access_token
from config import BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE_URL = "https://open.feishu.cn/open-apis"

TARGET_FIELD = "①游戏·投放平台"
NEW_OPTIONS   = ["小红书"]   # 追加的选项，可按需扩充


def get_headers():
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json",
    }


def list_fields():
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields"
    r = requests.get(url, headers=get_headers()).json()
    if r.get("code") != 0:
        raise Exception(f"list_fields 失败: {r.get('msg', r)}")
    return r["data"]["items"]


def patch_field(field_id, current_options):
    """用现有选项 + 新选项一起 patch（飞书需要传完整 options 列表）"""
    existing_names = {o["name"] for o in current_options}
    to_add = [n for n in NEW_OPTIONS if n not in existing_names]
    if not to_add:
        print(f"  ✓ 「{TARGET_FIELD}」已包含所有目标选项，无需修改")
        return

    merged = current_options + [{"name": n} for n in to_add]
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields/{field_id}"
    body = {"property": {"options": merged}}
    r = requests.patch(url, headers=get_headers(), json=body).json()
    if r.get("code") != 0:
        raise Exception(f"patch_field 失败: {r.get('msg', r)}")
    print(f"  ✓ 已追加选项：{to_add}")


def main():
    print(f"[add_game_platform_options] 目标字段：{TARGET_FIELD}")
    fields = list_fields()
    target = next((f for f in fields if f["field_name"] == TARGET_FIELD), None)
    if not target:
        print(f"  ✗ 未找到字段「{TARGET_FIELD}」，请确认字段名")
        sys.exit(1)

    field_id       = target["field_id"]
    current_options = target.get("property", {}).get("options", [])
    print(f"  当前选项（{len(current_options)} 个）：{[o['name'] for o in current_options]}")
    patch_field(field_id, current_options)
    print("[add_game_platform_options] 完成")


if __name__ == "__main__":
    main()
