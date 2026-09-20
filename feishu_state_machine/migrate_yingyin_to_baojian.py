"""
一次性迁移：v4 多维表格 影音 段 → 保健食品 段

7 个字段重命名 + options 重写：
  ①影音·物料类型      → ①保健食品·物料类型      （单选 options 微调）
  ①影音·投放平台      → ①保健食品·投放平台      （多选 options 重写：去掉爱奇艺/腾讯视频/优酷，加电商）
  ①影音·内容类型      → ①保健食品·产品品类      （单选 options 整套换）
  ①影音·物料涉及场景  → ①保健食品·物料涉及场景  （文本，仅改名）
  ①影音·AIGC使用声明  → ①保健食品·核心宣称功效  （单选 → 多选；options 换为 27 项保健功能目录）
  ①影音·作品名称      → ①保健食品·产品备案名称  （文本，仅改名）
  ①影音·IP名称        → ①保健食品·批准文号      （文本，仅改名）

并：
  ①运营·行业领域 单选 option：影音 → 保健食品

⚠️ 此脚本只跑一次，跑完线上 v4 表立刻反映新结构。
"""
import time
import requests
from config import BITABLE_APP_TOKEN, BITABLE_TABLE_ID
from feishu_api import get_tenant_access_token

BASE = "https://open.feishu.cn/open-apis"
FT_TEXT, FT_SELECT, FT_MULTI = 1, 3, 4

# ===== 字段重命名+重写定义 =====

INDUSTRY_OPTION_RENAME = {
    # 行业领域单选 option name 改名（option_id 保持，会保留历史数据）
    "影音": "保健食品",
}

FIELD_MIGRATIONS = [
    # 文本字段：只改名
    {"old": "①影音·物料涉及场景", "new": "①保健食品·物料涉及场景",
     "type": FT_TEXT},
    {"old": "①影音·作品名称", "new": "①保健食品·产品备案名称",
     "type": FT_TEXT},
    {"old": "①影音·IP名称", "new": "①保健食品·批准文号",
     "type": FT_TEXT},

    # 单选 — 物料类型（options 微调，去掉"预告片"加"直播话术"）
    {"old": "①影音·物料类型", "new": "①保健食品·物料类型",
     "type": FT_SELECT,
     "property": {"options": [
         {"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
         {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"},
     ]}},

    # 多选 — 投放平台（替换为电商导向平台组合）
    {"old": "①影音·投放平台", "new": "①保健食品·投放平台",
     "type": FT_MULTI,
     "property": {"options": [
         {"name": "抖音"}, {"name": "小红书"}, {"name": "微信"},
         {"name": "B站"}, {"name": "淘宝"}, {"name": "天猫"},
         {"name": "京东"}, {"name": "拼多多"}, {"name": "微博"},
         {"name": "快手"}, {"name": "视频号"}, {"name": "其他"},
     ]}},

    # 单选 — 产品品类
    {"old": "①影音·内容类型", "new": "①保健食品·产品品类",
     "type": FT_SELECT,
     "property": {"options": [
         {"name": "维生素/矿物质"}, {"name": "益生菌/膳食纤维"},
         {"name": "蛋白粉/氨基酸"}, {"name": "鱼油/卵磷脂"},
         {"name": "中草药提取"}, {"name": "营养代餐"},
         {"name": "运动补给"}, {"name": "其他"},
     ]}},

    # 单选 → 多选 — 核心宣称功效（《允许保健食品声称的保健功能目录 2023版》27 项 + 营养素补充剂）
    {"old": "①影音·AIGC使用声明", "new": "①保健食品·核心宣称功效",
     "type": FT_MULTI,
     "property": {"options": [
         {"name": "增强免疫力"}, {"name": "辅助降血脂"}, {"name": "辅助降血糖"},
         {"name": "抗氧化"}, {"name": "辅助改善记忆"}, {"name": "缓解视疲劳"},
         {"name": "促进排铅"}, {"name": "清咽"}, {"name": "辅助降血压"},
         {"name": "改善睡眠"}, {"name": "促进泌乳"}, {"name": "缓解体力疲劳"},
         {"name": "提高缺氧耐受力"}, {"name": "对辐射危害有辅助保护功能"},
         {"name": "减肥"}, {"name": "改善生长发育"}, {"name": "增加骨密度"},
         {"name": "改善营养性贫血"}, {"name": "对化学性肝损伤的辅助保护"},
         {"name": "祛痤疮"}, {"name": "祛黄褐斑"}, {"name": "改善皮肤水分"},
         {"name": "改善皮肤油分"}, {"name": "调节肠道菌群"}, {"name": "促进消化"},
         {"name": "通便"}, {"name": "对胃黏膜损伤有辅助保护"},
         {"name": "营养素补充剂"},
     ]}},
]


def list_fields(h):
    items, page_token = [], None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields",
                         headers=h, params=params).json()
        items.extend(r["data"]["items"])
        if not r["data"].get("has_more"):
            break
        page_token = r["data"].get("page_token")
    return items


def update_field(h, field_id, payload):
    """PUT /fields/{field_id} 修改字段名/类型/options"""
    r = requests.put(
        f"{BASE}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields/{field_id}",
        headers=h, json=payload,
    ).json()
    return r


def main():
    token = get_tenant_access_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    print("【1】 拉取当前字段...")
    fields = list_fields(h)
    name2field = {f["field_name"]: f for f in fields}
    print(f"    共 {len(fields)} 个字段")

    # ===== Step 2：行业领域 option 改名 =====
    print("\n【2】 改 ①运营·行业领域 选项「影音」→「保健食品」")
    industry_field = name2field.get("①运营·行业领域")
    if not industry_field:
        print("    ✗ 未找到 ①运营·行业领域 字段，跳过")
    else:
        new_options = []
        for opt in industry_field["property"]["options"]:
            if opt["name"] in INDUSTRY_OPTION_RENAME:
                new_name = INDUSTRY_OPTION_RENAME[opt["name"]]
                # 保留 option id 让历史选择记录不丢
                new_options.append({"id": opt["id"], "name": new_name})
                print(f"    {opt['name']} → {new_name}  (option_id={opt['id']})")
            else:
                new_options.append({"id": opt["id"], "name": opt["name"]})
        r = update_field(h, industry_field["field_id"], {
            "field_name": "①运营·行业领域",
            "type": FT_SELECT,
            "property": {"options": new_options},
        })
        print(f"    code={r.get('code')}, msg={r.get('msg')}")

    time.sleep(0.3)

    # ===== Step 3：迁移 7 个 影音 字段 =====
    print(f"\n【3】 迁移 {len(FIELD_MIGRATIONS)} 个影音字段...")
    for mig in FIELD_MIGRATIONS:
        old_field = name2field.get(mig["old"])
        if not old_field:
            print(f"    ✗ 未找到 {mig['old']}，跳过")
            continue
        payload = {
            "field_name": mig["new"],
            "type": mig["type"],
        }
        if "property" in mig:
            payload["property"] = mig["property"]

        r = update_field(h, old_field["field_id"], payload)
        if r.get("code") == 0:
            print(f"    ✓ {mig['old']:30s} → {mig['new']}")
        else:
            print(f"    ✗ {mig['old']:30s} → {mig['new']}  code={r.get('code')} msg={r.get('msg')}")
        time.sleep(0.25)

    # ===== Step 4：复核 =====
    print("\n【4】 复核（拉一次最新字段列表）...")
    fields_after = list_fields(h)
    leftover_yingyin = [f["field_name"] for f in fields_after if "影音" in f["field_name"]]
    new_baojian = [f["field_name"] for f in fields_after if "保健食品" in f["field_name"]]
    print(f"    影音残留: {len(leftover_yingyin)} 个 {leftover_yingyin}")
    print(f"    保健食品段: {len(new_baojian)} 个")
    for n in new_baojian:
        print(f"      ✓ {n}")

    # 行业领域确认
    industry_field2 = next((f for f in fields_after if f["field_name"] == "①运营·行业领域"), None)
    if industry_field2:
        opts = [o["name"] for o in industry_field2["property"]["options"]]
        print(f"    ①运营·行业领域 当前选项: {opts}")

    print("\n" + "=" * 60)
    if not leftover_yingyin and len(new_baojian) == 7:
        print("✅ 迁移完成")
    else:
        print("⚠️  迁移未完整完成，请检查日志")
    print("=" * 60)


if __name__ == "__main__":
    main()
