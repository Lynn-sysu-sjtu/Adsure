"""
建好运营表单视图，并隐藏所有非"①运营提交段"字段。

⚠️ 飞书表单字段配置 API 应用身份只能改 visible，
   required / description / title / 条件显示，需要在网页手动配置。

跑完后输出表单分享链接。
"""
import requests, time
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE = "https://open.feishu.cn/open-apis"
FORM_NAME = "运营物料提交表单"


def get_token():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]


def list_views(h):
    r = requests.get(f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/views",
                     headers=h, params={"page_size": 100}).json()
    return r["data"]["items"]


def list_form_fields(h, view_id):
    items, page_token = [], None
    while True:
        params = {"page_size": 100}
        if page_token: params["page_token"] = page_token
        r = requests.get(
            f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/forms/{view_id}/fields",
            headers=h, params=params).json()
        items.extend(r["data"]["items"])
        if not r["data"].get("has_more"): break
        page_token = r["data"].get("page_token")
    return items


def patch_form_field(h, view_id, field_id, visible):
    r = requests.patch(
        f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/forms/{view_id}/fields/{field_id}",
        headers=h, json={"visible": visible}).json()
    return r


def main():
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. 找/建表单视图
    print("【1】 查现有视图...")
    views = list_views(h)
    form = next((v for v in views if v.get("view_type") == "form" and v.get("view_name") == FORM_NAME), None)
    if form:
        view_id = form["view_id"]
        print(f"    已存在: {view_id}")
    else:
        print(f"    创建新表单视图...")
        r = requests.post(
            f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/views",
            headers=h, json={"view_name": FORM_NAME, "view_type": "form"}).json()
        view_id = r["data"]["view"]["view_id"]
        print(f"    ✓ {view_id}")

    # 2. 列表单字段
    print(f"\n【2】 列字段...")
    fields = list_form_fields(h, view_id)
    print(f"    共 {len(fields)} 个")

    # 3. 批量改可见性
    # 规则: 以 ① 开头的全部 visible=True；其他全部 visible=False
    # 例外：①运营·提交人 / ①运营·提交时间 由系统自动填，对运营也隐藏
    AUTO_HIDDEN_OPS = {"①运营·提交人", "①运营·提交时间"}
    print(f"\n【3】 配置可见性...")
    show, hide = 0, 0
    for f in fields:
        title = f["title"]
        is_ops = title.startswith("①")
        is_auto = title in AUTO_HIDDEN_OPS
        visible = is_ops and not is_auto
        r = patch_form_field(h, view_id, f["field_id"], visible)
        if r.get("code") == 0:
            mark = "👁" if visible else "🚫"
            print(f"    {mark} {title}")
            if visible: show += 1
            else: hide += 1
        else:
            print(f"    ✗ {title}: {r.get('msg')}")
        time.sleep(0.1)

    print(f"\n    显示 {show} 个，隐藏 {hide} 个")

    # 4. 取分享链接（如未开启共享则需手动开）
    print(f"\n【4】 查表单元信息...")
    r = requests.get(
        f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/forms/{view_id}",
        headers=h).json()
    form = r.get("data", {}).get("form", {})
    print(f"    名称: {form.get('name')}")
    print(f"    已开启分享: {form.get('shared')}")
    print(f"    分享链接: {form.get('shared_url') or '（需到网页打开分享）'}")

    print("\n" + "=" * 60)
    print("✅ 表单视图已建+字段可见性已配置")
    print(f"  view_id = {view_id}")
    print(f"  打开看看: https://dcnhexeh6nru.feishu.cn/base/{BITABLE_APP_TOKEN}?table={BITABLE_TABLE_ID}&view={view_id}")
    print()
    print("⚠️ API 限制，下面这些需要你手动在网页里配置：")
    print("  1. 行业字段的【条件显示】规则:")
    print("     - 美妆专属6字段：仅当 行业领域=美妆 时显示")
    print("     - 游戏专属6字段：仅当 行业领域=游戏 时显示")
    print("     - 保健食品专属7字段：仅当 行业领域=保健食品 时显示")
    print("  2. 必填字段：行业领域/物料编号/物料内容/紧急程度/是否启用AI预审")
    print("  3. 表单标题/描述：建议改为「审心·广告物料合规审核提交单」")
    print("  4. 开启表单分享，复制公开链接给运营")
    print("=" * 60)


if __name__ == "__main__":
    main()
