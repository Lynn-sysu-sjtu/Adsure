"""
通过 wiki 节点 token 反查它对应的多维表格 app_token

适用场景：你的多维表格是建在飞书知识库（wiki）内，
URL 长这样: https://xxx.feishu.cn/wiki/{node_token}?table={table_id}
此时 wiki 节点 token 不能直接当 app_token 使用，需要通过 API 转换。

使用：
  1. 在 WIKI_NODE_TOKEN 处填入你的 wiki 节点 token
  2. python3 resolve_wiki_token.py
  3. 拿到输出的 app_token，更新到 config.py 的 BITABLE_APP_TOKEN
"""
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET

BASE_URL = "https://open.feishu.cn/open-apis"

# ===== 这是从你 wiki URL 里复制出来的 =====
# https://dcnhexeh6nru.feishu.cn/wiki/BBPDwTfWCipm3Gk8SYRcDkxPnTg?table=tblzaR1H6TRCfMri
WIKI_NODE_TOKEN = "VeAbwXEalioPTGkcgnhceGQznEc"
TABLE_ID = ""  # 新链接没有 ?table=... 部分


def get_token():
    url = f"{BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取token失败: {data}")
    return data["tenant_access_token"]


def main():
    print("【1】 获取 access token...")
    token = get_token()
    print(f"    OK: {token[:16]}...\n")

    print(f"【2】 解析 wiki 节点 {WIKI_NODE_TOKEN}...")
    url = f"{BASE_URL}/wiki/v2/spaces/get_node"
    params = {"token": WIKI_NODE_TOKEN, "obj_type": "wiki"}
    resp = requests.get(url,
        headers={"Authorization": f"Bearer {token}"},
        params=params)
    data = resp.json()

    print(f"    返回 code={data.get('code')}, msg={data.get('msg')}")
    if data.get("code") != 0:
        print(f"\n❌ 解析失败")
        print(f"完整返回: {data}")
        print("\n常见原因:")
        print("  1. 飞书应用没开 wiki:wiki 或 wiki:node:read 权限")
        print("     → 去开发者后台 - 权限管理 - 搜 wiki - 开启 - 发布")
        print("  2. 应用没被加入到这个wiki空间")
        print("     → 去wiki空间 - 设置 - 成员管理 - 把你的应用加进去")
        return

    node = data["data"]["node"]
    print()
    print("=" * 60)
    print("✅ 解析成功")
    print(f"   wiki node_token: {WIKI_NODE_TOKEN}")
    print(f"   obj_type: {node.get('obj_type')}")
    print(f"   ⭐ obj_token (= app_token): {node.get('obj_token')}")
    print(f"   title: {node.get('title')}")
    print()
    print("下一步:")
    print(f"  1. 更新 config.py:")
    print(f'     BITABLE_APP_TOKEN = "{node.get("obj_token")}"')
    print(f'     BITABLE_TABLE_ID  = "{TABLE_ID}"')
    print(f"  2. 跑 python3 setup_bitable_v2.py 在这个wiki多维表格里建字段")
    print("=" * 60)


if __name__ == "__main__":
    main()
