"""
v3 多维表格构建脚本（应用自建，权限自带）

设计要点（与用户v3讨论一致）:
  ① 运营提交区  — 公共字段 + 美妆/游戏/影音 行业专属字段（A方案：表单条件显示 → 多维表格落库）
  ② AI预审区    — 给运营看的轻量辅助
  ③ AI审核区    — 给法务看的深度审核
  ④ 法务裁决区  — 法务终审
  ⑤ 流转沉淀区  — 状态/反馈/大脑沉淀

字段命名约定：用 "段·名" 前缀让飞书 UI 自然按段排序展示；
分组"组"如果 API 不支持，会给手动归组步骤。

跑法: python3 create_bitable_v3.py
"""
import requests
import time
from config import FEISHU_APP_ID, FEISHU_APP_SECRET

BASE_URL = "https://open.feishu.cn/open-apis"
NEW_NAME = "审心广告物料合规审核台 v3"

# 字段类型常量
FT_TEXT = 1
FT_NUMBER = 2
FT_SELECT = 3
FT_MULTI = 4
FT_DATE = 5
FT_CHECK = 7
FT_USER = 11
FT_ATTACH = 17

FIELDS = [
    # ===== ① 运营提交区 — 公共 =====
    {"field_name": "①运营·物料编号", "type": FT_TEXT},
    {"field_name": "①运营·行业领域", "type": FT_SELECT,
     "property": {"options": [{"name": "美妆"}, {"name": "游戏"}, {"name": "影音"}]}},
    {"field_name": "①运营·物料内容", "type": FT_TEXT},
    {"field_name": "①运营·物料附件", "type": FT_ATTACH},
    {"field_name": "①运营·提交人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "①运营·提交时间", "type": FT_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "①运营·紧急程度", "type": FT_SELECT,
     "property": {"options": [{"name": "普通"}, {"name": "加急"}]}},
    {"field_name": "①运营·是否启用AI预审", "type": FT_SELECT,
     "property": {"options": [{"name": "是"}, {"name": "否"}]}},

    # ===== ① 运营提交区 — 美妆专属 =====
    {"field_name": "①美妆·物料类型", "type": FT_SELECT,
     "property": {"options": [
         {"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
         {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "①美妆·投放平台", "type": FT_MULTI,
     "property": {"options": [
         {"name": "抖音"}, {"name": "小红书"}, {"name": "微信"},
         {"name": "B站"}, {"name": "淘宝"}, {"name": "微博"},
         {"name": "快手"}, {"name": "视频号"}, {"name": "其他"}]}},
    {"field_name": "①美妆·产品品类", "type": FT_SELECT,
     "property": {"options": [
         {"name": "护肤"}, {"name": "彩妆"}, {"name": "香水"},
         {"name": "个护"}, {"name": "美容仪器"}, {"name": "其他"}]}},
    {"field_name": "①美妆·产品备案名称", "type": FT_TEXT},
    {"field_name": "①美妆·物料涉及场景", "type": FT_TEXT},
    {"field_name": "①美妆·核心宣称功效", "type": FT_TEXT},

    # ===== ① 运营提交区 — 游戏专属 =====
    {"field_name": "①游戏·物料类型", "type": FT_SELECT,
     "property": {"options": [
         {"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
         {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "①游戏·投放平台", "type": FT_MULTI,
     "property": {"options": [
         {"name": "抖音"}, {"name": "B站"}, {"name": "微信"},
         {"name": "TapTap"}, {"name": "微博"}, {"name": "快手"},
         {"name": "视频号"}, {"name": "其他"}]}},
    {"field_name": "①游戏·产品品类", "type": FT_SELECT,
     "property": {"options": [
         {"name": "MMO"}, {"name": "MOBA"}, {"name": "卡牌"},
         {"name": "二次元"}, {"name": "SLG"}, {"name": "休闲"},
         {"name": "射击"}, {"name": "其他"}]}},
    {"field_name": "①游戏·游戏名称", "type": FT_TEXT},
    {"field_name": "①游戏·物料涉及场景", "type": FT_TEXT},
    {"field_name": "①游戏·IP名称", "type": FT_TEXT},

    # ===== ① 运营提交区 — 影音专属 =====
    {"field_name": "①影音·物料类型", "type": FT_SELECT,
     "property": {"options": [
         {"name": "图文"}, {"name": "短视频"}, {"name": "预告片"},
         {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "①影音·投放平台", "type": FT_MULTI,
     "property": {"options": [
         {"name": "抖音"}, {"name": "B站"}, {"name": "微信"},
         {"name": "微博"}, {"name": "快手"}, {"name": "视频号"},
         {"name": "爱奇艺"}, {"name": "腾讯视频"}, {"name": "优酷"}, {"name": "其他"}]}},
    {"field_name": "①影音·内容类型", "type": FT_SELECT,
     "property": {"options": [
         {"name": "电影"}, {"name": "电视剧"}, {"name": "综艺"},
         {"name": "动画"}, {"name": "网络短剧"}, {"name": "纪录片"}, {"name": "其他"}]}},
    {"field_name": "①影音·物料涉及场景", "type": FT_TEXT},
    {"field_name": "①影音·AIGC使用声明", "type": FT_SELECT,
     "property": {"options": [
         {"name": "未使用AIGC"}, {"name": "部分使用AIGC"},
         {"name": "全部AIGC生成"}, {"name": "未声明"}]}},
    {"field_name": "①影音·作品名称", "type": FT_TEXT},
    {"field_name": "①影音·IP名称", "type": FT_TEXT},

    # ===== ② AI预审区（给运营） =====
    {"field_name": "②AI预审·风险等级", "type": FT_SELECT,
     "property": {"options": [
         {"name": "高", "color": 0}, {"name": "中", "color": 1},
         {"name": "低", "color": 2}, {"name": "无明显风险", "color": 3}]}},
    {"field_name": "②AI预审·命中要点", "type": FT_TEXT},
    {"field_name": "②AI预审·修改建议", "type": FT_TEXT},
    {"field_name": "②AI预审·时间", "type": FT_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "②AI预审·运营修改记录", "type": FT_TEXT},
    {"field_name": "②AI预审·运营是否采纳建议", "type": FT_SELECT,
     "property": {"options": [
         {"name": "全部采纳"}, {"name": "部分采纳"},
         {"name": "未采纳"}, {"name": "未使用预审"}]}},

    # ===== ③ AI审核区（给法务） =====
    {"field_name": "③AI审核·审核模式", "type": FT_SELECT,
     "property": {"options": [
         {"name": "极速"}, {"name": "标准"}, {"name": "深度"}]}},
    {"field_name": "③AI审核·模式推荐理由", "type": FT_TEXT},
    {"field_name": "③AI审核·审核意见", "type": FT_TEXT},
    {"field_name": "③AI审核·关键实体抽取", "type": FT_TEXT},
    {"field_name": "③AI审核·高风险词命中", "type": FT_TEXT},
    {"field_name": "③AI审核·平台规则预检", "type": FT_TEXT},
    {"field_name": "③AI审核·备案核查结果", "type": FT_TEXT},
    {"field_name": "③AI审核·推荐违规类型", "type": FT_MULTI,
     "property": {"options": [
         {"name": "绝对化用语"}, {"name": "虚假宣传"},
         {"name": "功效超备案"}, {"name": "涉医疗宣传"},
         {"name": "数据引用不规范"}, {"name": "概率造假"},
         {"name": "未成年人保护"}, {"name": "版号缺失"},
         {"name": "AIGC未标识"}, {"name": "许可证缺失"},
         {"name": "广告不可识别"}, {"name": "大小字误导"},
         {"name": "擦边低俗"}, {"name": "IP侵权"}, {"name": "其他"}]}},
    {"field_name": "③AI审核·推荐风险等级", "type": FT_SELECT,
     "property": {"options": [
         {"name": "高", "color": 0}, {"name": "中", "color": 1}, {"name": "低", "color": 2}]}},
    {"field_name": "③AI审核·审核时间", "type": FT_DATE,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},

    # ===== ④ 法务裁决区 =====
    {"field_name": "④法务·AI意见评价", "type": FT_SELECT,
     "property": {"options": [
         {"name": "同意无补充"}, {"name": "同意有补充"}, {"name": "驳回"}]}},
    {"field_name": "④法务·物料裁决", "type": FT_SELECT,
     "property": {"options": [{"name": "通过"}, {"name": "不通过"}]}},
    {"field_name": "④法务·异议字段", "type": FT_MULTI,
     "property": {"options": [
         {"name": "风险等级"}, {"name": "违规类型"},
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

    # ===== ⑤ 流转沉淀区 =====
    {"field_name": "⑤流转·当前状态", "type": FT_SELECT,
     "property": {"options": [
         {"name": "运营起草"}, {"name": "AI预审中"},
         {"name": "运营修改中"}, {"name": "待法务复核"},
         {"name": "已通过"}, {"name": "需修改"},
         {"name": "已上线"}, {"name": "已撤回"}]}},
    {"field_name": "⑤流转·反馈类型", "type": FT_SELECT,
     "property": {"options": [
         {"name": "refine"}, {"name": "override"}, {"name": "无"}]}},
    {"field_name": "⑤流转·是否进入大脑沉淀", "type": FT_CHECK},
    {"field_name": "⑤流转·驳回次数", "type": FT_NUMBER, "property": {"formatter": "0"}},
    {"field_name": "⑤流转·轮次", "type": FT_NUMBER, "property": {"formatter": "0"}},
]


def get_token():
    r = requests.post(f"{BASE_URL}/auth/v3/tenant_access_token/internal",
                      json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    return r.json()["tenant_access_token"]


def main():
    print("【1】 获取 token...")
    token = get_token()
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"    OK\n")

    print(f"【2】 创建 「{NEW_NAME}」（应用所有，权限自带）...")
    r = requests.post(f"{BASE_URL}/bitable/v1/apps", headers=h,
                      json={"name": NEW_NAME}).json()
    print(f"    code={r.get('code')}, msg={r.get('msg')}")
    if r.get("code") != 0:
        print(f"    完整: {r}")
        return
    app = r["data"]["app"]
    app_token = app["app_token"]
    new_url = app.get("url", f"https://feishu.cn/base/{app_token}")
    print(f"    ✓ app_token = {app_token}")
    print(f"    ✓ URL = {new_url}\n")

    print("【3】 列出默认表...")
    r = requests.get(f"{BASE_URL}/bitable/v1/apps/{app_token}/tables", headers=h).json()
    if r.get("code") != 0:
        print(f"    失败: {r}"); return
    table_id = r["data"]["items"][0]["table_id"]
    print(f"    ✓ table_id = {table_id}\n")

    print("【4】 读取主字段...")
    r = requests.get(f"{BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
                     headers=h).json()
    primary = r["data"]["items"][0]
    print(f"    ✓ 主字段: {primary['field_name']} ({primary['field_id']})\n")

    print(f"【5】 重命名主字段为「{FIELDS[0]['field_name']}」...")
    r = requests.put(
        f"{BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{primary['field_id']}",
        headers=h, json=FIELDS[0]).json()
    print(f"    code={r.get('code')}, msg={r.get('msg')}")
    time.sleep(0.3)

    print(f"\n【6】 添加剩余 {len(FIELDS)-1} 个字段...")
    add_url = f"{BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    ok = 0
    fail = []
    for i, fd in enumerate(FIELDS[1:], start=2):
        r = requests.post(add_url, headers=h, json=fd).json()
        if r.get("code") == 0:
            ok += 1
            print(f"    [{i:2d}/{len(FIELDS)}] ✓ {fd['field_name']}")
        else:
            fail.append((fd['field_name'], r.get('msg')))
            print(f"    [{i:2d}/{len(FIELDS)}] ✗ {fd['field_name']} → {r.get('msg')}")
        time.sleep(0.25)

    print("\n" + "=" * 60)
    print(f"✅ 完成: 字段 {ok+1}/{len(FIELDS)}")
    if fail:
        print(f"⚠ 失败 {len(fail)} 个:")
        for n, m in fail: print(f"   - {n}: {m}")
    print()
    print("【新表信息（请更新到 config.py）】")
    print(f'  BITABLE_APP_TOKEN = "{app_token}"')
    print(f'  BITABLE_TABLE_ID  = "{table_id}"')
    print(f"  URL = {new_url}")
    print("=" * 60)


if __name__ == "__main__":
    main()
