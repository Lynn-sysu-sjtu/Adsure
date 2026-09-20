"""
v4 一气呵成：建表 → 建字段 → 建分组 → 转让所有权
"""
import requests, time
from config import FEISHU_APP_ID, FEISHU_APP_SECRET

BASE = "https://open.feishu.cn/open-apis"
NEW_NAME = "审心广告物料合规审核台 v4"
USER_MOBILE = "13395778231"

FT_TEXT, FT_NUMBER, FT_SELECT, FT_MULTI = 1, 2, 3, 4
FT_DATE, FT_CHECK, FT_USER, FT_ATTACH = 5, 7, 11, 17

FIELDS = [
    {"field_name": "①运营·物料编号", "type": FT_TEXT},
    {"field_name": "①运营·行业领域", "type": FT_SELECT,
     "property": {"options": [{"name": "美妆"}, {"name": "游戏"}, {"name": "保健食品"}]}},
    {"field_name": "①运营·物料内容", "type": FT_TEXT},
    {"field_name": "①运营·物料附件", "type": FT_ATTACH},
    {"field_name": "①运营·提交人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "①运营·提交时间", "type": FT_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "①运营·紧急程度", "type": FT_SELECT,
     "property": {"options": [{"name": "普通"}, {"name": "加急"}]}},
    {"field_name": "①运营·是否启用AI预审", "type": FT_SELECT,
     "property": {"options": [{"name": "是"}, {"name": "否"}]}},
    {"field_name": "①美妆·物料类型", "type": FT_SELECT,
     "property": {"options": [{"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
                              {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "①美妆·投放平台", "type": FT_MULTI,
     "property": {"options": [{"name": "抖音"}, {"name": "小红书"}, {"name": "微信"},
                              {"name": "B站"}, {"name": "淘宝"}, {"name": "微博"},
                              {"name": "快手"}, {"name": "视频号"}, {"name": "其他"}]}},
    {"field_name": "①美妆·产品品类", "type": FT_SELECT,
     "property": {"options": [{"name": "护肤"}, {"name": "彩妆"}, {"name": "香水"},
                              {"name": "个护"}, {"name": "美容仪器"}, {"name": "其他"}]}},
    {"field_name": "①美妆·产品备案名称", "type": FT_TEXT},
    {"field_name": "①美妆·物料涉及场景", "type": FT_TEXT},
    {"field_name": "①美妆·核心宣称功效", "type": FT_TEXT},
    {"field_name": "①游戏·物料类型", "type": FT_SELECT,
     "property": {"options": [{"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
                              {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "①游戏·投放平台", "type": FT_MULTI,
     "property": {"options": [{"name": "抖音"}, {"name": "小红书"}, {"name": "B站"}, {"name": "微信"},
                              {"name": "TapTap"}, {"name": "微博"}, {"name": "快手"},
                              {"name": "视频号"}, {"name": "其他"}]}},
    {"field_name": "①游戏·产品品类", "type": FT_SELECT,
     "property": {"options": [{"name": "MMO"}, {"name": "MOBA"}, {"name": "卡牌"},
                              {"name": "二次元"}, {"name": "SLG"}, {"name": "休闲"},
                              {"name": "射击"}, {"name": "其他"}]}},
    {"field_name": "①游戏·游戏名称", "type": FT_TEXT},
    {"field_name": "①游戏·物料涉及场景", "type": FT_TEXT},
    {"field_name": "①游戏·IP名称", "type": FT_TEXT},
    {"field_name": "①保健食品·物料类型", "type": FT_SELECT,
     "property": {"options": [{"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
                              {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "①保健食品·投放平台", "type": FT_MULTI,
     "property": {"options": [{"name": "抖音"}, {"name": "小红书"}, {"name": "微信"},
                              {"name": "B站"}, {"name": "淘宝"}, {"name": "天猫"}, {"name": "京东"},
                              {"name": "拼多多"}, {"name": "微博"}, {"name": "快手"},
                              {"name": "视频号"}, {"name": "其他"}]}},
    {"field_name": "①保健食品·产品品类", "type": FT_SELECT,
     "property": {"options": [{"name": "维生素/矿物质"}, {"name": "益生菌/膳食纤维"},
                              {"name": "蛋白粉/氨基酸"}, {"name": "鱼油/卵磷脂"},
                              {"name": "中草药提取"}, {"name": "营养代餐"},
                              {"name": "运动补给"}, {"name": "其他"}]}},
    {"field_name": "①保健食品·物料涉及场景", "type": FT_TEXT},
    {"field_name": "①保健食品·核心宣称功效", "type": FT_MULTI,
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
         {"name": "营养素补充剂"}]}},
    {"field_name": "①保健食品·产品备案名称", "type": FT_TEXT},
    {"field_name": "①保健食品·批准文号", "type": FT_TEXT},
    {"field_name": "②AI预审·风险等级", "type": FT_SELECT,
     "property": {"options": [{"name": "高", "color": 0}, {"name": "中", "color": 1},
                              {"name": "低", "color": 2}, {"name": "无明显风险", "color": 3}]}},
    {"field_name": "②AI预审·命中要点", "type": FT_TEXT},
    {"field_name": "②AI预审·修改建议", "type": FT_TEXT},
    {"field_name": "②AI预审·时间", "type": FT_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "②AI预审·运营修改记录", "type": FT_TEXT},
    {"field_name": "②AI预审·运营是否采纳建议", "type": FT_SELECT,
     "property": {"options": [{"name": "全部采纳"}, {"name": "部分采纳"},
                              {"name": "未采纳"}, {"name": "未使用预审"}]}},
    {"field_name": "③AI审核·审核模式", "type": FT_SELECT,
     "property": {"options": [{"name": "极速"}, {"name": "标准"}, {"name": "深度"}]}},
    {"field_name": "③AI审核·模式推荐理由", "type": FT_TEXT},
    {"field_name": "③AI审核·审核意见", "type": FT_TEXT},
    {"field_name": "③AI审核·关键实体抽取", "type": FT_TEXT},
    {"field_name": "③AI审核·高风险词命中", "type": FT_TEXT},
    {"field_name": "③AI审核·平台规则预检", "type": FT_TEXT},
    {"field_name": "③AI审核·备案核查结果", "type": FT_TEXT},
    {"field_name": "③AI审核·推荐违规类型", "type": FT_MULTI,
     "property": {"options": [{"name": "绝对化用语"}, {"name": "虚假宣传"},
                              {"name": "功效超备案"}, {"name": "涉医疗宣传"},
                              {"name": "数据引用不规范"}, {"name": "概率造假"},
                              {"name": "未成年人保护"}, {"name": "版号缺失"},
                              {"name": "AIGC未标识"}, {"name": "许可证缺失"},
                              {"name": "广告不可识别"}, {"name": "大小字误导"},
                              {"name": "擦边低俗"}, {"name": "IP侵权"}, {"name": "其他"}]}},
    {"field_name": "③AI审核·推荐风险等级", "type": FT_SELECT,
     "property": {"options": [{"name": "高", "color": 0}, {"name": "中", "color": 1}, {"name": "低", "color": 2}]}},
    {"field_name": "③AI审核·审核时间", "type": FT_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "④法务·AI意见评价", "type": FT_SELECT,
     "property": {"options": [{"name": "同意无补充"}, {"name": "同意有补充"}, {"name": "驳回"}]}},
    {"field_name": "④法务·物料裁决", "type": FT_SELECT,
     "property": {"options": [{"name": "通过"}, {"name": "不通过"}]}},
    {"field_name": "④法务·异议字段", "type": FT_MULTI,
     "property": {"options": [{"name": "风险等级"}, {"name": "违规类型"},
                              {"name": "高风险词识别"}, {"name": "备案核查"},
                              {"name": "法条依据"}, {"name": "修改建议"},
                              {"name": "整体推理逻辑"}, {"name": "其他"}]}},
    {"field_name": "④法务·补充或驳回理由", "type": FT_TEXT},
    {"field_name": "④法务·驳回正确判定", "type": FT_TEXT},
    {"field_name": "④法务·最终修改意见", "type": FT_TEXT},
    {"field_name": "④法务·批注", "type": FT_TEXT},
    {"field_name": "④法务·复核人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "④法务·复核时间", "type": FT_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "⑤流转·当前状态", "type": FT_SELECT,
     "property": {"options": [{"name": "运营起草"}, {"name": "AI预审中"},
                              {"name": "运营修改中"}, {"name": "待法务复核"},
                              {"name": "已通过"}, {"name": "需修改"},
                              {"name": "已上线"}, {"name": "已撤回"}]}},
    {"field_name": "⑤流转·反馈类型", "type": FT_SELECT,
     "property": {"options": [{"name": "refine"}, {"name": "override"}, {"name": "无"}]}},
    {"field_name": "⑤流转·是否进入大脑沉淀", "type": FT_CHECK},
    {"field_name": "⑤流转·驳回次数", "type": FT_NUMBER, "property": {"formatter": "0"}},
    {"field_name": "⑤流转·轮次", "type": FT_NUMBER, "property": {"formatter": "0"}},
]

GROUPS = [("①", "①运营提交区"), ("②", "②AI预审区"), ("③", "③AI审核区"),
          ("④", "④法务裁决区"), ("⑤", "⑤流转沉淀区")]


def get_token():
    r = requests.post(f"{BASE}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]


def main():
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print("【1】 创建 v4 多维表格...")
    r = requests.post(f"{BASE}/bitable/v1/apps", headers=h, json={"name": NEW_NAME}).json()
    if r.get("code") != 0:
        print(f"    失败: {r}"); return
    app_token = r["data"]["app"]["app_token"]
    new_url = r["data"]["app"].get("url", f"https://feishu.cn/base/{app_token}")
    print(f"    ✓ {app_token}\n    ✓ {new_url}\n")

    print("【2】 默认表+主字段...")
    r = requests.get(f"{BASE}/bitable/v1/apps/{app_token}/tables", headers=h).json()
    table_id = r["data"]["items"][0]["table_id"]
    r = requests.get(f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields", headers=h).json()
    primary = r["data"]["items"][0]
    junk_ids = [x["field_id"] for x in r["data"]["items"] if not x.get("is_primary")]
    print(f"    table_id={table_id}, 主字段={primary['field_id']}, 垃圾字段={len(junk_ids)}")

    print(f"\n【3】 重命名主字段 → {FIELDS[0]['field_name']}")
    requests.put(f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{primary['field_id']}",
                 headers=h, json=FIELDS[0])
    time.sleep(0.3)

    print(f"\n【4】 删除默认垃圾字段 {len(junk_ids)} 个...")
    for fid in junk_ids:
        requests.delete(f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{fid}", headers=h)
        time.sleep(0.15)

    print(f"\n【5】 添加 {len(FIELDS)-1} 个字段...")
    add_url = f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    name2id = {primary["field_name"]: primary["field_id"]}  # 主字段已重命名
    name2id[FIELDS[0]["field_name"]] = primary["field_id"]
    for i, fd in enumerate(FIELDS[1:], start=2):
        r = requests.post(add_url, headers=h, json=fd).json()
        if r.get("code") == 0:
            name2id[fd["field_name"]] = r["data"]["field"]["field_id"]
            print(f"    [{i:2d}/{len(FIELDS)}] ✓ {fd['field_name']}")
        else:
            print(f"    [{i:2d}/{len(FIELDS)}] ✗ {fd['field_name']} {r.get('msg')}")
        time.sleep(0.2)

    print(f"\n【6】 创建 5 个字段分组...")
    payload = []
    for prefix, gname in GROUPS:
        ids = [name2id[fd["field_name"]] for fd in FIELDS
               if fd["field_name"].startswith(prefix) and fd["field_name"] != FIELDS[0]["field_name"]]
        print(f"    {gname}: {len(ids)} 个")
        if ids:
            payload.append({"name": gname, "children": [{"id": fid, "type": "field"} for fid in ids]})
    r = requests.post(f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/field_groups",
                      headers=h, json={"field_groups": payload}).json()
    print(f"    code={r.get('code')}, msg={r.get('msg')}")
    if r.get("code") == 0:
        for g in r.get("data", {}).get("field_groups", []):
            print(f"      ✓ {g.get('name')} (id={g.get('field_group_id')})")

    print(f"\n【7】 转让所有权给 {USER_MOBILE}...")
    rr = requests.post(f"{BASE}/contact/v3/users/batch_get_id?user_id_type=open_id",
                       headers=h, json={"mobiles": [USER_MOBILE], "include_resigned": False}).json()
    if rr.get("code") == 0 and rr["data"].get("user_list"):
        oid = rr["data"]["user_list"][0].get("user_id")
        if oid:
            r = requests.post(f"{BASE}/drive/v1/permissions/{app_token}/members/transfer_owner",
                              headers=h,
                              params={"type": "bitable", "need_notification": "true"},
                              json={"member_type": "openid", "member_id": oid,
                                    "old_owner_perm": "full_access"}).json()
            print(f"    转让结果: code={r.get('code')}, msg={r.get('msg')}")
        else:
            print(f"    ❌ 没拿到 open_id: {rr}")
    else:
        print(f"    ❌ 查询用户失败: {rr}")

    print("\n" + "=" * 60)
    print("✅ v4 全流程完成")
    print(f'  BITABLE_APP_TOKEN = "{app_token}"')
    print(f'  BITABLE_TABLE_ID  = "{table_id}"')
    print(f"  URL = {new_url}")
    print("=" * 60)


if __name__ == "__main__":
    main()
