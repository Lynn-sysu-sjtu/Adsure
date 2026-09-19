#!/usr/bin/env python3
"""按 8 个广告处罚缺口场景，低频检索浙江行政处罚结果公开 API。

合规边界：
- 只访问公开 searchPunishList / punishDetail，不使用登录、Cookie、验证码或 token；
- RobotsGate 硬门禁，同主机请求间隔不少于 3 秒；
- 原始列表/详情逐次写入 data/raw_text/zj_xzcf/gap_20260917/；
- 仅把详情全文同时命中“强场景词 + 商业广告/宣传语境 + 市场监管广告/反不正当竞争依据”
  的记录写为 structured_candidates，状态固定为 pending_human_review、approved_for_rag=false。

本脚本不把北大法宝司法案例当成行政处罚事实；司法/行政参考另做人审报告。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.crawler.policy import RobotsGate, RateLimiter, build_ssl_context, UA  # noqa: E402
import urllib.request  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
LIST_API = "https://xzcf.zjzwfw.gov.cn/api-gateway/jpaas-punishment-server/open-api/punishment/searchPunishList"
DETAIL_API = "https://xzcf.zjzwfw.gov.cn/api-gateway/jpaas-punishment-server/open-api/punishment/punishDetail"
DETAIL_PAGE = "https://xzcf.zjzwfw.gov.cn/punishment/#/punishdetails"

SCENARIOS = [
    {
        "id": "s01_minor_protection",
        "name": "未成年人保护",
        "queries": ["诱导未成年人", "未成年人消费", "儿童广告"],
        "fallback_queries": ["未成年", "儿童", "小学生"],
        "dimensions": ["未成年人保护", "诱导未成年人消费", "广告合规"],
        "confirm": [r"诱导.{0,24}(未成年|儿童|小学生)", r"(未成年|儿童|小学生|中小学生|幼儿|中小学校|幼儿园).{0,90}(广告|宣传|消费|充值|游戏)", r"(广告|宣传).{0,90}(未成年|儿童|小学生|中小学生|幼儿|中小学校|幼儿园)"],
        "negative": [r"售烟|销售烟|烟草|酒精|售酒|酒水|文身|纹身|未成年工|职业病|交通|学校食堂"],
    },
    {
        "id": "s02_game_license_antiaddiction",
        "name": "版号/防沉迷",
        "queries": ["游戏版号", "防沉迷广告", "网络游戏广告"],
        "fallback_queries": ["防沉迷", "实名制", "网络游戏", "版号", "未实名", "游戏"],
        "dimensions": ["网络游戏广告", "游戏版号", "防沉迷/实名制"],
        "confirm": [r"(版号|防沉迷|实名(?:制|认证)|未实名).{0,50}(广告|宣传|游戏|网络)", r"(网络游戏|游戏).{0,50}(版号|防沉迷|实名(?:制|认证)|未实名)"],
        "negative": [],
    },
    {
        "id": "s03_platform_rules",
        "name": "平台规则类",
        "queries": ["直播带货", "信息流广告", "抖音广告"],
        "fallback_queries": ["小红书广告", "天猫广告", "京东广告", "互联网广告", "拼多多", "美团", "短视频广告", "朋友圈广告", "网店广告"],
        "dimensions": ["平台广告合规", "直播带货/信息流", "互联网广告"],
        "confirm": [r"(直播(?:带货|间)?|信息流广告|抖音|小红书|天猫|京东|淘宝|拼多多|视频号|网店|电商).{0,60}(广告|宣传|虚假|误导)"],
        "negative": [r"城市照明|城市道路|散发商业性广告|户外广告设施|市容|张贴|悬挂"],
    },
    {
        "id": "s04_endorsement",
        "name": "广告代言",
        "queries": ["广告代言", "明星代言", "代言人广告"],
        "fallback_queries": ["代言", "网红推荐", "推荐官", "体验官", "推荐证明", "受益者名义", "形象作推荐"],
        "dimensions": ["广告代言", "推荐证明", "互联网广告"],
        "confirm": [r"(代言(?:人)?|明星代言|网红(?:推荐|代言)|推荐官|体验官).{0,70}(广告|宣传|推荐|证明|虚假|误导)", r"(医疗|药品|医疗器械)?广告中作推荐、?证明", r"(广告|宣传).{0,30}作推荐、?证明", r"利用受益者的名义或者形象作推荐、?证明"],
        "negative": [],
    },
    {
        "id": "s05_edible_cosmetics",
        "name": "化妆品可食用",
        "queries": ["可食用化妆品", "食品级化妆品", "儿童化妆品广告"],
        "fallback_queries": ["化妆品", "可食用", "食品级", "润唇膏", "食用级", "唇膏", "可以吃"],
        "dimensions": ["化妆品广告", "可食用/食品级误导", "儿童化妆品"],
        "confirm": [r"(化妆品|护肤品|润唇膏|口红|儿童化妆品).{0,70}(可食用|食品级|食用级|可以吃|可吃|口服)", r"(可食用|食品级|食用级|可以吃|可吃).{0,70}(化妆品|护肤品|润唇膏|口红|儿童化妆品)"],
        "negative": [],
    },
    {
        "id": "s06_gift_promotion",
        "name": "买赠规则",
        "queries": ["买一送一广告", "买赠广告", "满减广告"],
        "fallback_queries": ["买一送一", "买赠", "赠品", "满减", "促销广告", "赠送", "促销", "返现"],
        "dimensions": ["促销广告", "买赠/满减", "价格或赠品表示不清"],
        "confirm": [r"(买一送一|买\d+得\d+|买赠|赠品|满减|赠送|促销|限时立减|限时特价|减价|折价).{0,100}(广告|宣传|虚假|误导|无法兑现|价格|期限|规定|行为)", r"(?:违反促销行为规定|规范促销行为|价格促销)"],
        "negative": [],
    },
    {
        "id": "s07_game_cashout",
        "name": "游戏收益/提现",
        "queries": ["游戏提现", "游戏收益", "日赚广告"],
        "fallback_queries": ["提现", "日赚", "红包提现", "游戏广告", "赚钱", "红包", "赚钱游戏", "看广告赚钱"],
        "dimensions": ["游戏广告", "收益/提现误导", "虚假宣传"],
        "confirm": [r"(游戏|红包).{0,70}(提现|日赚|收益|赚钱|提现失败|虚假)", r"(提现|日赚|收益|赚钱).{0,70}(游戏|红包|广告|宣传)"],
        "negative": [],
    },
    {
        "id": "s08_data_citation",
        "name": "数据引证",
        "queries": ["好评率广告", "销量虚假广告", "下载量广告"],
        "fallback_queries": ["好评率", "销量", "下载量", "数据来源", "临床数据", "成交占比", "排名", "销冠", "无出处"],
        "dimensions": ["数据引证不规范", "虚假宣传", "广告数据无出处"],
        "confirm": [r"(好评率|销量|销售量|下载量|数据来源|临床数据|排名|成交占比|TOP\s*1|占比\s*\d+(?:\.\d+)?%|超\s*\d+(?:\.\d+)?%).{0,90}(无出处|无法提供|虚构|不实|虚假|没有依据|广告|宣传)", r"(广告|宣传).{0,90}(好评率|销量|销售量|下载量|数据来源|临床数据|排名|成交占比).{0,70}(无出处|无法提供|虚构|不实|虚假|没有依据)?", r"刷单.{0,80}(虚构|虚假).{0,80}(交易|销量|用户评价|评价)", r"虚构交易(?:单数)?(?:和)?(?:虚假的)?用户评价|虚假的用户评价"],
        "negative": [],
    },
]

COMMON_FALLBACK = ["违法广告", "虚假广告", "虚假宣传", "医疗用语", "绝对化用语", "保健食品", "化妆品", "互联网广告", "广告"]
NOISE_TITLE = re.compile(r"城市照明|城市道路|散发商业性广告|户外广告设施|非广告的户外设施|市容|张贴|悬挂|招牌|酒精制品|售烟|销售烟|烟草|文身|纹身|未成年工|职业病|摩托车|交通违法")
AD_CONTEXT = re.compile(r"广告|宣传|虚假|误导|代言人|直播|电商|网店")
# 除广告法/反法外，也保留广告审查专门规章与促销价格规章中的商业广告/促销处罚；全部仍待人核。
AD_LEGAL_BASIS = re.compile(r"广告法|反不正当竞争法|广告审查管理|互联网广告管理办法|规范促销行为暂行规定|中华人民共和国价格法")
MARKET_AUTHORITY = re.compile(r"市场监督管理局|市场监管")


@dataclass
class Hit:
    item: dict
    scenarios: dict[str, list[str]] = field(default_factory=dict)
    list_paths: set[str] = field(default_factory=set)
    queries: set[str] = field(default_factory=set)
    score: int = 0


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def slug(s: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "_", s, flags=re.UNICODE).strip("_")
    return s[:80] or "query"


def post_form(url: str, fields: dict[str, str], timeout: int = 45) -> dict:
    boundary = "AdsureCaseBotGapBoundary"
    body = []
    for key, value in fields.items():
        body.append(f"--{boundary}\r\n".encode())
        body.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.append(f"{value}\r\n".encode("utf-8"))
    body.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url,
        data=b"".join(body),
        headers={
            "User-Agent": UA,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=build_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def clean_html(s: str) -> str:
    s = s or ""
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s+", "\n", s)
    return s.strip()


def case_id(item: dict) -> str:
    raw = str(item.get("guid") or item.get("unid") or "")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^\w-]+", "_", raw).strip("_")[:48]
    return f"zj_gap_{safe or digest}"


def source_url(item: dict) -> str:
    return f"{DETAIL_PAGE}?guid={urllib.parse.quote(str(item.get('guid') or ''))}&unid={urllib.parse.quote(str(item.get('unid') or ''))}"


def title_score(item: dict, scenario: dict) -> int:
    title = item.get("xzcfws_name") or ""
    authority = item.get("orgnode") or ""
    score = 0
    if MARKET_AUTHORITY.search(authority):
        score += 20
    if AD_CONTEXT.search(title):
        score += 20
    if not NOISE_TITLE.search(title):
        score += 10
    for term in scenario["queries"] + scenario.get("fallback_queries", []):
        if term and term in title:
            score += 12
    if re.search(r"广告中含有虚假内容|虚假广告|虚假宣传|违法广告", title):
        score += 8
    if NOISE_TITLE.search(title):
        score -= 80
    return score


def select_detail_targets(hits: dict[str, Hit], max_per_scenario: int) -> dict[str, Hit]:
    selected: dict[str, Hit] = {}
    for scenario in SCENARIOS:
        sid = scenario["id"]
        candidates = [h for h in hits.values() if sid in h.scenarios]
        candidates.sort(key=lambda h: (h.score, h.item.get("xzcf_date", "")), reverse=True)
        for h in candidates[:max_per_scenario]:
            selected[str(h.item.get("guid") or h.item.get("unid"))] = h
    return selected


def confirmed_scenarios(text: str, title: str) -> tuple[dict[str, list[str]], list[str]]:
    # 只以处罚全文 xzcf_zy 确认事实；案名可用于人审线索，但不能在全文缺事实时自动入场景。
    hay = text
    matches: dict[str, list[str]] = {}
    evidence: list[str] = []
    for scenario in SCENARIOS:
        if any(re.search(p, hay, re.I | re.S) for p in scenario.get("negative", [])):
            continue
        terms_found = []
        for pattern in scenario["confirm"]:
            m = re.search(pattern, hay, re.I | re.S)
            if m:
                terms_found.append(m.group(0))
                evidence.append(m.group(0))
        if terms_found:
            matches[scenario["id"]] = sorted(set(terms_found))[:5]
    return matches, sorted(set(evidence))[:10]


def split_sections(text: str) -> tuple[str, str]:
    facts = ""
    penalty = ""
    m = re.search(r"主要违法事实[:：]\s*(.*?)\s*行政处罚种类、依据、内容[:：]", text, re.S)
    if m:
        facts = m.group(1).strip()
    m = re.search(r"行政处罚种类、依据、内容[:：]\s*(.*?)\s*(?:行政处罚履行方式和期限[:：]|$)", text, re.S)
    if m:
        penalty = m.group(1).strip()
    return facts, penalty


def extract_amount(penalty: str) -> float | None:
    # 只解析阿拉伯数字罚款金额；中文大写金额保留在 penalty_result，人工复核，不臆造。
    matches = re.findall(r"罚款(?:人民币)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元", penalty)
    if not matches:
        return None
    try:
        return float(matches[-1].replace(",", ""))
    except ValueError:
        return None


def extract_legal_basis(text: str) -> list[str]:
    out = []
    for raw in re.findall(r"《[^》]+》(?:第[〇零一二三四五六七八九十百千万0-9]+条(?:之[一二三四五六七八九十])?)?", text):
        title = raw.split("》", 1)[0] + "》"
        # 合同、嵌套引用的答复/裁判口径等不作为处罚法律依据。
        nested_or_reply = title.count("《") != 1 or title.startswith("《最高人民法院")
        is_law = (not nested_or_reply) and bool(re.search(r"(?:法|条例|办法|规定|规则|决定|细则|解释)》$", title))
        if is_law and raw not in out:
            out.append(raw)
    return out


def extract_claims(text: str, evidence: list[str], limit: int = 6) -> list[str]:
    claims = []
    for q in re.findall(r"[“\"]([^”\"]{2,100})[”\"]", text):
        q = q.strip()
        if q and not q.startswith("中华人民共和国") and q not in claims:
            claims.append(q)
    for e in evidence:
        e = re.sub(r"\s+", "", e)
        if 4 <= len(e) <= 100 and e not in claims:
            claims.append(e)
    return claims[:limit]


def infer_industry(text: str) -> str:
    if re.search(r"培训学校|培训效果|培训服务|职业技能培训", text):
        return "教育培训"
    if re.search(r"养生馆|瑶浴|推拿|按摩|筋膜|足浴|美容舱|生物共振", text):
        return "养生保健/生活服务"
    if re.search(r"网络游戏|游戏广告|游戏收益", text):
        return "游戏"
    if re.search(r"药店|口服溶液|药品零售", text):
        return "药品零售"
    if re.search(r"儿童化妆品|化妆品|润唇膏|口红|护肤品|护发霜", text):
        return "化妆品"
    if re.search(r"房地产|楼盘|住房|商品房|大平层", text):
        return "房地产"
    if re.search(r"电动升降桌|电脑桌|书桌|家具", text):
        return "家具/电商"
    if re.search(r"保健食品|保健品|普通食品|食品", text):
        return "食品/保健食品"
    if re.search(r"口腔门诊部|眼科|眼视光|门诊部|医疗|药品|医疗器械|医美", text):
        return "医疗/医药"
    return ""


def infer_product(text: str, industry: str) -> str:
    if industry == "教育培训":
        return "培训服务广告"
    if industry == "养生保健/生活服务":
        if re.search(r"瑶浴.{0,20}(全身)?按摩|瑶浴\+全身按摩", text):
            return "“瑶浴+全身按摩”养生服务"
        if re.search(r"生物共振|美容器|芯片舱", text):
            return "家用皮肤美容器/生物共振设备体验服务"
        return "养生保健服务"
    if industry == "游戏" and re.search(r"网络游戏|游戏广告|游戏收益", text):
        return "网络游戏/游戏广告"
    if industry == "药品零售":
        m = re.search(r"葡萄糖酸钙锌口服溶液", text) or re.search(r"[\u4e00-\u9fa5A-Za-z0-9]{2,20}?(?:胶囊|颗粒)", text)
        if m and re.search(r"买\d+得\d+|赠送药品", text):
            return f"{m.group(0)}药品买赠广告"
        return "药品/药品零售广告"
    if industry == "化妆品":
        m = re.search(r"(润嘉丽)(?:产品)?", text)
        if m:
            return "润嘉丽普通化妆品"
        if re.search(r"护发霜", text):
            return "化妆品（山茶玫瑰护发霜；广告主项为养生服务）"
        for pat in [r"儿童化妆品", r"润唇膏", r"口红", r"化妆品", r"护肤品"]:
            m = re.search(pat, text)
            if m:
                return m.group(0)
    if industry == "房地产":
        return "房地产广告"
    if industry == "家具/电商":
        return "电动升降桌/电脑桌等网店促销商品"
    if industry == "食品/保健食品":
        return "食品/保健食品广告"
    if industry == "医疗/医药":
        if re.search(r"口腔|门诊部", text) and re.search(r"诊疗项目", text):
            return "口腔门诊诊疗项目医疗广告"
        m = re.search(r"超级双效希爱力|男性勃起功能障碍.{0,20}药品", text)
        if m:
            return "进口药品（超级双效希爱力）网络销售及宣传"
        if re.search(r"眼视光|验光|配镜|角膜塑形镜", text):
            return "眼科医疗广告（医学验光配镜、斜弱视矫正、角膜塑形镜验配等）"
        return "医疗广告（公开全文未披露具体产品/服务名称）"
    return ""


def infer_channel(text: str) -> str | None:
    digital = []
    checks = [
        (r"抖音店铺|抖音账号|抖音", "抖音"),
        (r"直播(?:带货|间)?", "网络直播"),
        (r"信息流广告", "信息流广告"),
        (r"小红书号|小红书", "小红书"),
        (r"视频号", "微信视频号"),
        (r"微信公众号|公众号", "微信公众号"),
        (r"微信朋友圈|朋友圈", "微信朋友圈"),
        (r"微信群", "微信群"),
        (r"天猫", "天猫"),
        (r"京东", "京东"),
        (r"淘宝店铺|淘宝闪购|淘宝", "淘宝"),
        (r"拼多多", "拼多多"),
        (r"美团外卖|美团", "美团"),
        (r"网店|电子商务平台|电商平台|网络店铺|网络经营", "电商平台"),
    ]
    for pattern, label in checks:
        if re.search(pattern, text, re.I) and label not in digital:
            digital.append(label)
    if digital:
        return "、".join(digital)
    offline = []
    for pattern, label in [(r"户外广告|广告位", "户外广告"), (r"宣传单|知情书|印刷品广告", "校园/印刷品宣传"), (r"经营场所", "经营场所宣传")]:
        if re.search(pattern, text, re.I):
            offline.append(label)
    return "、".join(offline) if offline else None


def risk_dimensions_for(sid: str, text: str) -> list[str]:
    if sid == "s01_minor_protection":
        if re.search(r"不满十周岁|未成年人作为广告代言人", text):
            return ["未成年人保护", "广告代言", "不满十周岁未成年人代言"]
        if re.search(r"中小学校|中小学|幼儿园|中小学生|幼儿", text):
            return ["未成年人保护", "校园广告", "医疗/广告审查合规"]
        return ["未成年人保护", "诱导未成年人消费", "广告合规"]
    if sid == "s02_game_license_antiaddiction":
        return ["网络游戏广告", "版号/防沉迷/实名制监管", "互联网内容合规"]
    if sid == "s03_platform_rules":
        dims = ["平台广告合规"]
        if re.search(r"直播", text): dims.append("直播带货")
        if re.search(r"信息流", text): dims.append("信息流广告")
        if re.search(r"电商平台|电子商务平台|网店|天猫|京东|淘宝|拼多多|抖音|小红书", text): dims.append("电商平台广告")
        dims.append("虚假/误导广告")
        return dims
    if sid == "s04_endorsement":
        dims = ["广告代言", "推荐证明"]
        if re.search(r"医疗|药品|医疗器械", text): dims.append("医疗广告推荐证明")
        return dims
    if sid == "s05_edible_cosmetics":
        return ["化妆品广告", "可食用/食品级误导", "儿童化妆品"]
    if sid == "s06_gift_promotion":
        return ["促销广告", "买赠/满减", "赠品或价格表示不清"]
    if sid == "s07_game_cashout":
        return ["游戏广告", "收益/提现误导", "虚假宣传"]
    if sid == "s08_data_citation":
        return ["数据引证不规范", "虚假宣传", "广告数据无出处"]
    return []


def claims_for(scenario_matches: dict[str, list[str]], text: str, evidence: list[str]) -> list[str]:
    claims = []
    def add(x):
        x = re.sub(r"\s+", " ", x).strip(" ；;，,。")
        if x and x not in claims and not x.startswith("中华人民共和国"):
            claims.append(x)
    if "s01_minor_protection" in scenario_matches:
        if re.search(r"中小学校|幼儿园", text): add("在中小学校、幼儿园或者利用与中小学生、幼儿有关的物品发布广告")
        if re.search(r"不满十周岁|未成年人作为广告代言人", text): add("利用不满十周岁的未成年人作为广告代言人")
    if "s03_platform_rules" in scenario_matches:
        if re.search(r"未经广告审查.{0,20}小红书|小红书号.{0,20}医疗广告", text): add("未经广告审查机关审查，在小红书官方账号发布医疗广告")
        if re.search(r"无法提供.{0,20}依据.{0,20}与事实不符|与事实不符", text): add("平台医疗广告内容无法提供依据且与事实不符")
        if re.search(r"抖音.{0,80}(治疗|疾病|医疗术语|改善)", text): add("在抖音短视频广告中宣称设备可治疗疾病、使用医疗术语或宣称疾病症状改善效果")
        if re.search(r"润嘉丽|普通化妆品", text):
            m = re.search(r"宣传其经营的润嘉丽产品具有(.{2,40}?)功效", text)
            if m: add(f"普通化妆品宣称“{m.group(1)}”功效")
            add("普通化妆品实际功效为保湿、舒缓，却作超出实际功效的宣传")
        if re.search(r"泡瑶浴|提高机体免疫力|排.*湿气|寒气", text):
            for q in re.findall(r"[“\"]([^”\"]{6,140})[”\"]", text):
                if any(t in q for t in ["泡瑶浴", "免疫力", "湿气", "寒气", "代谢"]): add(q)
        if re.search(r"产地、性能.{0,20}(不准确|不清楚|不明白)", text): add("拼多多网店广告对商品产地、性能等表示不准确、不清楚、不明白")
        if re.search(r"电商平台.{0,20}虚假广告", text): add("在电商平台发布虚假广告")
    if "s04_endorsement" in scenario_matches:
        if re.search(r"受益者的名义或者形象", text): add("利用受益者的名义或者形象作推荐、证明")
        add("在医疗、药品、医疗器械广告中作推荐、证明" if re.search(r"药品|医疗器械|医疗广告", text) else "在广告中作推荐、证明")
    if "s06_gift_promotion" in scenario_matches:
        m = re.search(r"买\d+得\d+", text)
        if m:
            add(f"发布“{m.group(0)}”等买赠/赠送宣传广告")
        if re.search(r"赠送药品广告|买\d+得\d+", text): add("发布赠送药品广告")
        if re.search(r"限时(?:立减|特价|减价|折价)|减价|折价", text) and re.search(r"未.{0,20}(标明|注明).{0,10}期限|未显著标明期限", text):
            add("开展限时减价、折价等价格促销活动未显著标明期限")
        if re.search(r"违反促销行为规定|规范促销行为", text): add("违反促销行为规定（公开全文未披露具体促销细节）")
    if "s08_data_citation" in scenario_matches:
        for q in re.findall(r"[“\"]([^”\"]{2,120})[”\"]", text):
            if any(t in q for t in ["TOP", "销冠", "占比", "好评", "销量", "下载", "数据"]): add(q)
        if re.search(r"数据无出处|虚构.{0,20}(数据|销售|排名|成交)", text): add("广告中的销量、排名、成交占比等数据无出处或系虚构")
        if re.search(r"刷单", text): add("通过刷单虚构交易单数")
        if re.search(r"虚假的用户评价|用户评价", text): add("形成虚假用户评价")
    return claims[:8]


def penalty_breakdown(penalty: str) -> dict:
    fines = [float(x.replace(",", "")) for x in re.findall(r"罚款(?:人民币)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元", penalty)]
    confiscation_amounts = [float(x.replace(",", "")) for x in re.findall(r"没收违法所得\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元", penalty)]
    ad_fine = None
    m = re.search(r"(?:二、|.*)(中小学校|幼儿园|广告|代言|代言人).{0,500}?罚款(?:人民币)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元", penalty, re.S)
    if m:
        try: ad_fine = float(m.group(2).replace(",", ""))
        except ValueError: ad_fine = None
    competition_fine = None
    competition_matches = list(re.finditer(r"反不正当竞争法.{0,700}?罚款(?:人民币)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*元", penalty, re.S))
    if competition_matches:
        try: competition_fine = float(competition_matches[-1].group(1).replace(",", ""))
        except ValueError: competition_fine = None
    return {
        "total_fine": fines[-1] if fines else None,
        "confiscated_illegal_gain": confiscation_amounts[-1] if confiscation_amounts else None,
        "total_monetary_penalty": (sum(fines[-1:]) + sum(confiscation_amounts[-1:])) or None,
        "advertising_related_fine_when_separable": ad_fine,
        "anti_unfair_competition_fine": competition_fine,
    }


def build_vector_text(item: dict, industry: str, channel: str | None, facts: str, penalty_result: str) -> str:
    party = item.get("bxzcf_name") or "当事人"
    location = f"通过{channel}发布相关宣传" if channel else "发布相关商业宣传"
    fact = re.sub(r"\s+", "", facts)
    fact = fact[:260] + ("……" if len(fact) > 260 else "")
    result = re.sub(r"\s+", "", penalty_result)
    result = result[:180] + ("……" if len(result) > 180 else "")
    prefix = f"这是浙江省行政处罚结果信息公开的一起{industry or '商业宣传'}广告处罚候选案例。"
    return f"{prefix}{party}{location}。处罚决定书写明：{fact}处罚结果为：{result}该记录来自行政机关公开处罚信息全文，仍需人工复核，暂不进入生产 RAG。"



def common_title_score(item: dict) -> int:
    title = item.get("xzcfws_name") or ""
    authority = item.get("orgnode") or ""
    score = 0
    if MARKET_AUTHORITY.search(authority):
        score += 30
    if re.search(r"广告中含有虚假内容|虚假广告|虚假宣传|违法广告|互联网广告", title):
        score += 30
    if AD_CONTEXT.search(title):
        score += 10
    if NOISE_TITLE.search(title):
        score -= 100
    return score


def select_generic_targets(hits: dict[str, Hit], cap: int) -> dict[str, Hit]:
    candidates = [h for h in hits.values() if "common" in h.scenarios and not NOISE_TITLE.search(h.item.get("xzcfws_name") or "")]
    candidates.sort(key=lambda h: (h.score, h.item.get("xzcf_date", "")), reverse=True)
    return {str(h.item.get("guid") or h.item.get("unid")): h for h in candidates[:cap]}


def collect_local_list_hits(batch: str) -> tuple[dict[str, Hit], list[dict]]:
    list_dir = ROOT / "data/raw_text/zj_xzcf" / batch / "list"
    hits: dict[str, Hit] = {}
    stats = []
    for path in sorted(list_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        fields = doc.get("request") or {}
        payload = doc.get("response") or {}
        parts = path.stem.split("__")
        sid = parts[0] if parts else "common"
        qtype = parts[1] if len(parts) > 1 else "local"
        kw = fields.get("xzcfws_name") or (parts[2] if len(parts) > 2 else "")
        page = int(fields.get("pageNo") or (parts[-1].lstrip("p") if parts[-1].startswith("p") else 1))
        data = payload.get("data") or {}
        items = data.get("punishList") or []
        scenario = next((x for x in SCENARIOS if x["id"] == sid), None)
        stats.append({"scenario_id": sid, "scenario": scenario["name"] if scenario else "通用兜底", "type": qtype, "keyword": kw, "page": page, "total": data.get("total"), "returned": len(items), "raw_path": f"data/raw_text/zj_xzcf/{batch}/list/{path.name}"})
        for item in items:
            key = str(item.get("guid") or item.get("unid"))
            h = hits.setdefault(key, Hit(item=item))
            h.scenarios.setdefault(sid, []).append(kw)
            h.queries.add(kw)
            h.list_paths.add(f"data/raw_text/zj_xzcf/{batch}/list/{path.name}")
            h.score = max(h.score, title_score(item, scenario) if scenario else common_title_score(item))
    return hits, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--begin", default="2020-01-01")
    ap.add_argument("--end", default="2026-09-17")
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--page-size", type=int, default=10)
    ap.add_argument("--max-details-per-scenario", type=int, default=6)
    ap.add_argument("--include-common-fallback", action="store_true")
    ap.add_argument("--common-only", action="store_true", help="只联网检索通用兜底词")
    ap.add_argument("--local-only", action="store_true", help="不联网，只从本批次已保存列表/详情重建候选和报告")
    ap.add_argument("--max-generic-details", type=int, default=24)
    ap.add_argument("--refresh-lists", action="store_true", help="即使已有列表原始返回也重新请求；默认复用缓存，低频补检")
    ap.add_argument("--lists-only", action="store_true", help="只检索并保存列表，不抓取/重建详情候选")
    ap.add_argument("--batch", default="gap_20260917")
    args = ap.parse_args()

    raw_dir = ROOT / "data/raw_text/zj_xzcf" / args.batch
    list_dir = raw_dir / "list"
    detail_dir = raw_dir / "detail"
    cand_dir = ROOT / "data/structured_candidates"
    report_dir = ROOT / "data/reports/source_verification"
    for p in (list_dir, detail_dir, cand_dir, report_dir):
        p.mkdir(parents=True, exist_ok=True)

    host = urllib.parse.urlparse(LIST_API).netloc
    limiter = RateLimiter(min_request_interval=3.2)
    fetched_at = now_iso()

    queries: list[tuple[str, str, str]] = []
    if args.local_only:
        hits, query_stats = collect_local_list_hits(args.batch)
    else:
        gate = RobotsGate()
        gate.check(LIST_API)
        gate.check(DETAIL_API)
        queries: list[tuple[str, str, str]] = []
        if not args.common_only:
            for scenario in SCENARIOS:
                for q in scenario["queries"]:
                    queries.append((scenario["id"], "primary", q))
                for q in scenario.get("fallback_queries", []):
                    queries.append((scenario["id"], "fallback", q))
        if args.include_common_fallback or args.common_only:
            for q in COMMON_FALLBACK:
                queries.append(("common", "common_fallback", q))

        hits = {}
        query_stats = []
    for sid, qtype, kw in (queries if not args.local_only else []):
        scenario_name = next((s["name"] for s in SCENARIOS if s["id"] == sid), "通用兜底")
        for page in range(1, args.pages + 1):
            fields = {
                "xzcfws_name": kw,
                "bxzcf_name": "",
                "xzcfws_code": "",
                "bxzcf_type": "",
                "begindate": args.begin,
                "enddate": args.end,
                "deptId": "",
                "areacode": "",
                "pageNo": str(page),
                "pageSize": str(args.page_size),
            }
            raw_rel = f"data/raw_text/zj_xzcf/{args.batch}/list/{sid}__{qtype}__{slug(kw)}__p{page}.json"
            raw_path = ROOT / raw_rel
            if raw_path.exists() and not args.refresh_lists:
                cached = json.loads(raw_path.read_text(encoding="utf-8"))
                payload = cached.get("response") or {}
                cached_note = "reused_cached_list"
            else:
                limiter.before_request(host)
                try:
                    payload = post_form(LIST_API, fields)
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    query_stats.append({"scenario_id": sid, "scenario": scenario_name, "type": qtype, "keyword": kw, "page": page, "error": f"{type(exc).__name__}: {exc}"})
                    print(f"[list-error] {sid} {kw} p{page}: {exc}", flush=True)
                    break
                raw_path.write_text(json.dumps({"fetched_at": fetched_at, "request": fields, "response": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
                cached_note = ""
            data = payload.get("data") or {}
            items = data.get("punishList") or []
            query_stats.append({"scenario_id": sid, "scenario": scenario_name, "type": qtype, "keyword": kw, "page": page, "total": data.get("total"), "returned": len(items), "raw_path": raw_rel, "note": cached_note})
            print(f"[list{'-cache' if cached_note else ''}] {sid} {kw} p{page}: {len(items)} / total {data.get('total')}", flush=True)
            if not items:
                break
            for item in items:
                key = str(item.get("guid") or item.get("unid"))
                h = hits.setdefault(key, Hit(item=item))
                h.scenarios.setdefault(sid, []).append(kw)
                h.queries.add(kw)
                h.list_paths.add(raw_rel)
                scenario = next((x for x in SCENARIOS if x["id"] == sid), None)
                h.score = max(h.score, title_score(item, scenario) if scenario else common_title_score(item))
            if page >= int(data.get("pageTotal") or page):
                break

    # 场景强词按场景取详情；通用兜底只拉市场监管广告标题，供全文二次扫描，避免城管“张贴广告”噪声。
    targets = select_detail_targets(hits, args.max_details_per_scenario)
    if args.include_common_fallback or args.common_only or args.local_only:
        for key, h in select_generic_targets(hits, args.max_generic_details).items():
            targets.setdefault(key, h)
    if args.local_only:
        # 重建报告时不联网；把本批次已经存证的每个详情都重新全文扫描一遍，避免 top-N 截断漏掉确认案例。
        targets = {}
        for path in sorted(detail_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            punish = ((doc.get("response") or doc).get("data") or {}).get("punish") or {}
            if not punish.get("guid") and not punish.get("unid"):
                continue
            item = {
                "guid": punish.get("guid") or punish.get("unid"),
                "unid": punish.get("unid") or punish.get("guid"),
                "xzcfws_name": punish.get("xzcfws_name") or "",
                "xzcfws_code": punish.get("xzcfws_code") or "",
                "bxzcf_name": punish.get("bxzcf_name") or "",
                "xzcf_date": punish.get("xzcf_date") or "",
                "orgnode": punish.get("orgnode") or "",
            }
            key = str(item["guid"])
            h = Hit(item=item)
            if key in hits:
                h.scenarios = dict(hits[key].scenarios)
                h.queries = set(hits[key].queries)
                h.list_paths = set(hits[key].list_paths)
                h.score = hits[key].score
            targets[key] = h
    detail_stats = []
    confirmed_rows = []

    if args.lists_only:
        targets = {}
    for idx, (key, h) in enumerate(sorted(targets.items(), key=lambda kv: (kv[1].item.get("xzcf_date") or ""), reverse=True), 1):
        item = h.item
        guid = str(item.get("guid") or "")
        unid = str(item.get("unid") or "")
        detail_rel = f"data/raw_text/zj_xzcf/{args.batch}/detail/{slug(guid or unid)}.json"
        detail_path = ROOT / detail_rel
        if detail_path.exists():
            detail_payload = json.loads(detail_path.read_text(encoding="utf-8"))
        elif args.local_only:
            detail_stats.append({"guid": guid, "title": item.get("xzcfws_name"), "status": "missing_local_detail", "raw_path": detail_rel})
            continue
        else:
            limiter.before_request(host)
            try:
                detail_payload = post_form(DETAIL_API, {"guid": guid, "unid": unid})
                detail_path.write_text(json.dumps({"fetched_at": now_iso(), "request": {"guid": guid, "unid": unid}, "response": detail_payload}, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[detail {idx}/{len(targets)}] {item.get('xzcfws_name')}", flush=True)
            except Exception as exc:  # details are evidence; failure stays in report
                detail_stats.append({"guid": guid, "title": item.get("xzcfws_name"), "error": f"{type(exc).__name__}: {exc}"})
                print(f"[detail-error] {item.get('xzcfws_name')}: {exc}", flush=True)
                continue

        punish = ((detail_payload.get("response") or detail_payload).get("data") or {}).get("punish") or {}
        full_raw = punish.get("xzcf_zy") or ""
        text = clean_html(full_raw)
        title = punish.get("xzcfws_name") or item.get("xzcfws_name") or ""
        matches, evidence = confirmed_scenarios(text, title)
        # 只保留商业广告处罚事实：市场监管机关 + 广告/反不正当竞争依据；跨部门仅进入参考统计，不入候选。
        is_market = bool(MARKET_AUTHORITY.search(punish.get("orgnode") or item.get("orgnode") or ""))
        is_ad_legal = bool(AD_LEGAL_BASIS.search(text))
        status = "confirmed" if matches and is_market and is_ad_legal else "not_confirmed"
        detail_stats.append({
            "guid": guid,
            "unid": unid,
            "title": title,
            "authority": punish.get("orgnode") or item.get("orgnode"),
            "scenario_matches": matches,
            "is_market_authority": is_market,
            "has_ad_legal_basis": is_ad_legal,
            "status": status,
            "raw_path": detail_rel,
        })
        if status != "confirmed":
            continue

        facts, penalty = split_sections(text)
        legal_basis = extract_legal_basis(text)
        amount = extract_amount(penalty)
        classification_context = f"{title}\n{text}"
        industry = infer_industry(classification_context) or "未披露（公开决定书未载明具体行业）"
        product = infer_product(classification_context, industry) or "未披露（公开决定书未载明具体商品/服务）"
        channel = infer_channel(classification_context)
        claims = claims_for(matches, text, evidence)
        dims = sorted({d for sid in matches for d in risk_dimensions_for(sid, text)})
        amount_breakdown = penalty_breakdown(penalty)
        consistency_notes = []
        if re.search(r"未成年人|代言|第三十八条", title) and not re.search(r"未成年人|代言|推荐|证明", text):
            consistency_notes.append("案名含未成年人/代言/广告法第三十八条表述，但处罚全文 xzcf_zy 未载明相应事实；场景标签仅按全文确认，案名与正文需人工核对。")
        if re.search(r"中小学校|幼儿园", text) and re.search(r"药品管理法|劣药|超过有效期", text):
            consistency_notes.append("同一决定书包含校园/未成年人相关广告违法与过期药品两项违法；penalty_amount 为合并罚款，广告分项罚款见 penalty_amount_breakdown。")
        if re.search(r"超过使用期限的.*化妆品|护发霜", text) and re.search(r"抖音.*广告|虚假广告", text):
            consistency_notes.append("同一决定书包含抖音虚假广告与过期化妆品/进货查验等非广告违法；广告分项罚款见 penalty_amount_breakdown。")
        if re.search(r"刷单|虚假的用户评价", text) and re.search(r"药品管理法|未取得药品|进口药品", text):
            consistency_notes.append("同一决定书包含无证/进口药品违法与刷单虚构交易、虚假评价；反不正当竞争分项罚款见 penalty_amount_breakdown.anti_unfair_competition_fine。")
        if re.search(r"未经广告审查.*医疗广告", text) and re.search(r"虚假广告", text):
            consistency_notes.append("同一决定书同时处理未经审查发布医疗广告和虚假广告；分项罚款见 penalty_amount_breakdown。")
        keywords = sorted(set([kw for kws in h.scenarios.values() for kw in kws] + [item.get("xzcfws_code") or ""]))
        cid = case_id(item)
        candidate = {
            "case_id": cid,
            "title": title,
            "case_number": punish.get("xzcfws_code") or item.get("xzcfws_code") or "",
            "source_type": "zj_xzcf_open_api_ad_gap_candidate",
            "source_name": "浙江省行政处罚结果信息公开（公开 API）",
            "source_url": source_url(item),
            "source_verification_status": "official_api_fulltext_pending_human_review",
            "source_lookup_priority": "P1",
            "publish_date": None,
            "decision_date": punish.get("xzcf_date") or item.get("xzcf_date") or None,
            "penalty_authority": punish.get("orgnode") or item.get("orgnode") or "",
            "party_name": punish.get("bxzcf_name") or item.get("bxzcf_name") or "",
            "region": (punish.get("orgnode") or item.get("orgnode") or "").replace("市场监督管理局", ""),
            "industry": industry,
            "product_or_service": product,
            "ad_channel": channel,
            "risk_dimensions": dims,
            "illegal_claims": claims,
            "facts_summary": facts,
            "legal_basis": legal_basis,
            "penalty_result": penalty,
            "penalty_amount": amount_breakdown["total_fine"],
            "penalty_amount_breakdown": amount_breakdown,
            "regulatory_logic": "以下监管逻辑仅概括决定书明示内容：处罚机关依据全文载明的广告/反不正当竞争事实及法条作出处理；场景映射、分项罚款与标题正文一致性仍需人工复核。",
            "mapped_rule_ids": [],
            "keywords": [k for k in keywords if k],
            "vector_text": build_vector_text(item, industry, channel, facts, penalty),
            "rag_chunk_type": "case_summary_candidate",
            "scope": "public",
            "case_nature": "administrative_penalty_decision",
            "is_admin_penalty_candidate": True,
            "is_administrative_penalty_fact": True,
            "gap_scenario_ids": sorted(matches.keys()),
            "gap_scenario_evidence": matches,
            "metadata_consistency_notes": consistency_notes,
            "review_status": "pending_human_review",
            "approved_for_rag": False,
            "human_review_required": True,
            "raw_text_path": detail_rel,
            "source_list_raw_paths": sorted(h.list_paths),
            "retrieved_at": now_iso(),
            "data_change_log": [{"ts": now_iso(), "action": "zj_gap_case_search", "note": "浙江公开 API 列表+详情命中 8 缺口强场景词；仅入候选，待人核，不进生产 RAG。"}],
        }
        out = cand_dir / f"{cid}.json"
        out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
        confirmed_rows.append({
            "case_id": cid,
            "title": title,
            "case_number": candidate["case_number"],
            "authority": candidate["penalty_authority"],
            "decision_date": candidate["decision_date"],
            "scenarios": sorted(matches.keys()),
            "amount": amount_breakdown["total_fine"],
            "advertising_related_fine": amount_breakdown.get("advertising_related_fine_when_separable"),
            "source_url": candidate["source_url"],
            "raw_text_path": detail_rel,
            "candidate_path": f"data/structured_candidates/{cid}.json",
        })

    manifest = {
        "generated_at": fetched_at,
        "batch": args.batch,
        "date_range": {"begin": args.begin, "end": args.end},
        "compliance": {
            "robots_gate": True,
            "min_request_interval_seconds": 3.2,
            "no_login_cookie_captcha_or_token": True,
            "candidates_not_production_rag": True,
        },
        "queries": query_stats,
        "unique_list_hits": len(hits),
        "detail_targets": len(targets),
        "details": detail_stats,
        "confirmed_rows": confirmed_rows,
    }
    manifest_path = report_dir / f"zj_gap_case_search_{args.batch}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = report_dir / f"zj_gap_case_search_{args.batch}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["case_id", "title", "case_number", "authority", "decision_date", "scenarios", "amount", "advertising_related_fine", "source_url", "raw_text_path", "candidate_path"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in confirmed_rows:
            r = dict(row)
            r["scenarios"] = ";".join(r["scenarios"])
            w.writerow(r)

    md_lines = [
        "# 浙江行政处罚公开 API：8 个广告缺口场景检索报告",
        "",
        f"- 批次：`{args.batch}`；时间范围：{args.begin} 至 {args.end}",
        f"- 原始列表唯一条目：{len(hits)}；拉取详情：{len(targets)}；确认入候选：{len(confirmed_rows)}",
        "- 合规：robots 硬门禁；同主机间隔 ≥3.2 秒；未使用登录/Cookie/验证码/token；候选均 `pending_human_review`，不进生产 RAG。",
        "",
        "## 分场景结果",
    ]
    for scenario in SCENARIOS:
        rows = [r for r in confirmed_rows if scenario["id"] in r["scenarios"]]
        md_lines.append(f"### {scenario['id']} {scenario['name']}")
        if not rows:
            md_lines.append("- 未在浙江 P1 行政处罚全文中确认到强匹配；列表检索证据保留在 manifest。")
        for r in rows:
            md_lines.append(f"- `{r['case_id']}` [{r['title']}]({r['source_url']})；{r['authority']}；{r['decision_date']}；详情：`{r['raw_text_path']}`")
        md_lines.append("")
    md_lines.extend(["## 查询统计", "", "| 场景 | 类型 | 关键词 | 页 | 返回 | 总量 | 原始返回 |", "|---|---:|---|---:|---:|---:|---|"])
    for q in query_stats:
        md_lines.append(f"| {q.get('scenario','')} | {q['type']} | {q['keyword']} | {q['page']} | {q.get('returned','')} | {q.get('total','')} | `{q.get('raw_path', q.get('error',''))}` |")
    md_path = report_dir / f"zj_gap_case_search_{args.batch}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print(json.dumps({"unique_list_hits": len(hits), "detail_targets": len(targets), "confirmed": len(confirmed_rows), "manifest": str(manifest_path), "report": str(md_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
