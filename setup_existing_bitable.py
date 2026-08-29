"""
在【现有空表】里直接建字段（不新建数据表）

适用场景：你已经在飞书wiki里手动建好了一个空多维表格，
现在要把35个字段加进去，并配置好类型。

前置条件：
  - 已跑过 resolve_wiki_token.py，拿到 app_token
  - 已更新 config.py 的 BITABLE_APP_TOKEN 和 BITABLE_TABLE_ID
  - 应用已被加入wiki空间，有可编辑权限

运行: python3 setup_existing_bitable.py
"""
import requests
import time
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, BITABLE_APP_TOKEN, BITABLE_TABLE_ID

BASE_URL = "https://open.feishu.cn/open-apis"

# 字段类型常量
FT_TEXT = 1
FT_NUMBER = 2
FT_SINGLE_SELECT = 3
FT_MULTI_SELECT = 4
FT_DATETIME = 5
FT_CHECKBOX = 7
FT_USER = 11
FT_ATTACHMENT = 17

# 字段定义（35个）
FIELDS = [
    # ① 运营提交
    {"field_name": "运营·物料编号", "type": FT_TEXT},
    {"field_name": "运营·物料内容", "type": FT_TEXT},
    {"field_name": "运营·物料附件", "type": FT_ATTACHMENT},
    {"field_name": "运营·行业领域", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "美妆"}, {"name": "游戏"}, {"name": "影音"}]}},
    {"field_name": "运营·物料类型", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "图文"}, {"name": "短视频"}, {"name": "直播话术"},
         {"name": "Banner"}, {"name": "详情页"}, {"name": "其他"}]}},
    {"field_name": "运营·投放平台", "type": FT_MULTI_SELECT,
     "property": {"options": [
         {"name": "抖音"}, {"name": "小红书"}, {"name": "微信"},
         {"name": "B站"}, {"name": "淘宝"}, {"name": "微博"},
         {"name": "快手"}, {"name": "视频号"}, {"name": "今日头条"}, {"name": "其他"}]}},
    {"field_name": "运营·是否启用AI预审", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "是"}, {"name": "否"}]}},
    {"field_name": "运营·紧急程度", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "普通"}, {"name": "加急"}]}},
    {"field_name": "运营·提交人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "运营·提交时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    # ② AI预审
    {"field_name": "AI预审·风险等级", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "高", "color": 0}, {"name": "中", "color": 1},
         {"name": "低", "color": 2}, {"name": "无明显风险", "color": 3}]}},
    {"field_name": "AI预审·命中要点", "type": FT_TEXT},
    {"field_name": "AI预审·修改建议", "type": FT_TEXT},
    {"field_name": "AI预审·时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    {"field_name": "AI预审·运营修改记录", "type": FT_TEXT},
    {"field_name": "AI预审·运营是否采纳建议", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "全部采纳"}, {"name": "部分采纳"},
         {"name": "未采纳"}, {"name": "未使用预审"}]}},
    # ③ AI审核
    {"field_name": "AI审核·审核意见", "type": FT_TEXT},
    {"field_name": "AI审核·高风险词命中", "type": FT_TEXT},
    {"field_name": "AI审核·备案核查结果", "type": FT_TEXT},
    {"field_name": "AI审核·推荐违规类型", "type": FT_MULTI_SELECT,
     "property": {"options": [
         {"name": "绝对化用语"}, {"name": "虚假宣传"},
         {"name": "功效超出备案"}, {"name": "医疗用语"},
         {"name": "数据引用不规范"}, {"name": "概率未公示"},
         {"name": "未成年人保护"}, {"name": "版号缺失"},
         {"name": "AIGC未标识"}, {"name": "许可证缺失"},
         {"name": "广告不可识别"}, {"name": "等价广告违规"},
         {"name": "含恐怖暴力内容"}, {"name": "其他"}]}},
    {"field_name": "AI审核·推荐风险等级", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "高", "color": 0}, {"name": "中", "color": 1}, {"name": "低", "color": 2}]}},
    {"field_name": "AI审核·审核时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    # ④ 法务裁决
    {"field_name": "法务·AI意见评价", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "同意无补充"}, {"name": "同意有补充"}, {"name": "驳回"}]}},
    {"field_name": "法务·物料裁决", "type": FT_SINGLE_SELECT,
     "property": {"options": [{"name": "通过"}, {"name": "不通过"}]}},
    {"field_name": "法务·异议字段", "type": FT_MULTI_SELECT,
     "property": {"options": [
         {"name": "风险等级"}, {"name": "违规类型"},
         {"name": "高风险词识别"}, {"name": "备案核查"}, {"name": "其他"}]}},
    {"field_name": "法务·补充或驳回理由", "type": FT_TEXT},
    {"field_name": "法务·驳回正确判定", "type": FT_TEXT},
    {"field_name": "法务·最终修改意见", "type": FT_TEXT},
    {"field_name": "法务·批注", "type": FT_TEXT},
    {"field_name": "法务·复核人", "type": FT_USER, "property": {"multiple": False}},
    {"field_name": "法务·复核时间", "type": FT_DATETIME,
     "property": {"date_formatter": "yyyy/MM/dd HH:mm"}},
    # ⑤ 流转沉淀
    {"field_name": "流转·当前状态", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "运营起草"}, {"name": "AI预审中"},
         {"name": "运营修改中"}, {"name": "待法务复核"},
         {"name": "已通过"}, {"name": "需修改"},
         {"name": "已上线"}, {"name": "已撤回"}]}},
    {"field_name": "流转·反馈类型", "type": FT_SINGLE_SELECT,
     "property": {"options": [
         {"name": "refine"}, {"name": "override"}, {"name": "无"}]}},
    {"field_name": "流转·是否进入大脑沉淀", "type": FT_CHECKBOX},
    {"field_name": "流转·轮次", "type": FT_NUMBER, "property": {"formatter": "0"}},
]


def get_token():
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取token失败: {data}")
    return data["tenant_access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_fields(token):
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields"
    resp = requests.get(url, headers=headers(token))
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"读取字段失败: {data}")
    return data["data"]["items"]


def update_field(token, field_id, field_def):
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields/{field_id}"
    resp = requests.put(url, headers=headers(token), json=field_def)
    return resp.json()


def create_field(token, field_def):
    url = f"{BASE_URL}/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/fields"
    resp = requests.post(url, headers=headers(token), json=field_def)
    return resp.json()


def main():
    print("【1】 获取 token...")
    token = get_token()
    print(f"    OK: {token[:16]}...\n")

    print(f"【2】 读取现有字段（app={BITABLE_APP_TOKEN[:10]}..., table={BITABLE_TABLE_ID}）...")
    existing = list_fields(token)
    existing_names = {f["field_name"] for f in existing}
    print(f"    现有 {len(existing)} 个字段: {list(existing_names)}\n")

    primary = existing[0]
    print(f"    主字段: id={primary['field_id']}, name={primary['field_name']}")

    print(f"\n【3】 重命名主字段为「{FIELDS[0]['field_name']}」...")
    if primary['field_name'] != FIELDS[0]['field_name']:
        resp = update_field(token, primary['field_id'], FIELDS[0])
        print(f"    code={resp.get('code')}, msg={resp.get('msg')}")
    else:
        print(f"    已是目标名，跳过")
    time.sleep(0.3)

    print(f"\n【4】 添加剩余 {len(FIELDS)-1} 个字段...")
    success = 0
    failed = []
    for i, fd in enumerate(FIELDS[1:], start=2):
        name = fd['field_name']
        if name in existing_names:
            print(f"    [{i}/{len(FIELDS)}] 跳过（已存在）: {name}")
            continue
        resp = create_field(token, fd)
        code = resp.get('code')
        if code == 0:
            success += 1
            print(f"    [{i}/{len(FIELDS)}] ✓ {name}")
        else:
            failed.append((name, resp.get('msg')))
            print(f"    [{i}/{len(FIELDS)}] ✗ {name} → {resp.get('msg')}")
        time.sleep(0.3)

    print("\n" + "=" * 60)
    print(f"✅ 完成: 新增 {success} 个字段")
    if failed:
        print(f"⚠ 失败: {len(failed)} 个")
        for name, msg in failed:
            print(f"   - {name}: {msg}")
    print("=" * 60)


if __name__ == "__main__":
    main()
