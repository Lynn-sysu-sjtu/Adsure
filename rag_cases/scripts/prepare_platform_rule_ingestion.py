#!/usr/bin/env python3
"""Prepare downloaded public platform-rule snapshots for human-reviewed ingestion.

The generated catalog is deliberately candidate-only.  It preserves source
URLs, raw snapshot hashes and extraction limitations, and never promotes a
platform rule into the production precheck catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VisibleTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


@dataclass(frozen=True)
class Source:
    source_id: str
    platform: str
    document_title: str
    url: str
    raw_path: str
    headers_path: str
    capture_format: str = "html"
    page_update_date: str | None = None
    intended_use: str = "platform_rule_candidate"
    notes: list[str] = field(default_factory=list)


SOURCES = [
    Source(
        "xhs_content_review_general_2026_03_23",
        "小红书",
        "内容审核规则总则",
        "https://ad.xiaohongshu.com/next_help/docs/8dc5bd9c45c9a90cb9912f3400d43f92",
        "data/platform_rules/raw_html/2026-09-04/xhs_content_review_general.html",
        "data/platform_rules/raw_html/2026-09-04/xhs_content_review_general.headers.txt",
        page_update_date="2026-03-23",
        notes=["页面采用动态渲染；下载HTML可能仅含应用外壳，候选条款来自同URL的浏览器可见正文核验。"],
    ),
    Source(
        "douyin_beauty_rules_notice_2022_05_10",
        "抖音电商",
        "关于《美妆行业宣传规范》修订的公示通知（2022.5.10）",
        "https://school.jinritemai.com/doudian/wap/article/aHUMNYPLL4Lk",
        "data/platform_rules/raw_html/2026-09-04/douyin_beauty_rules_2022.html",
        "data/platform_rules/raw_html/2026-09-04/douyin_beauty_rules_2022.headers.txt",
        page_update_date="2022-05-10",
        notes=["公示页面称规则预计于2022-05-17生效；正式适用状态仍需平台运营复核。"],
    ),
    Source(
        "douyin_beauty_rules_page_110681",
        "抖音电商",
        "美妆行业宣传规范（页面ID 110681）",
        "https://school.jinritemai.com/doudian/wap/article/110681?from=baiying_main&from_school=1&should_full_screen=1&should_hide_bottom_nav=1",
        "data/platform_rules/raw_html/2026-09-04/douyin_beauty_rules_current.html",
        "data/platform_rules/raw_html/2026-09-04/douyin_beauty_rules_current.headers.txt",
        notes=["动态页面；标题、版本和条款正文须通过实际商家后台再次核验。"],
    ),
    Source(
        "tencent_ads_skin_care_216",
        "腾讯广告",
        "护肤彩妆",
        "https://tencentads.com/Faqlist/Detail/216",
        "data/platform_rules/raw_html/2026-09-04/tencent_skin_care.html",
        "data/platform_rules/raw_html/2026-09-04/tencent_skin_care.headers.txt",
    ),
    Source(
        "taobao_live_seller_agreement_20220516174444172",
        "淘宝直播",
        "淘宝直播店卖家服务协议",
        "https://terms.alicdn.com/legal-agreement/terms/platform_service/20220516174444172/20220516174444172.html",
        "data/platform_rules/raw_html/2026-09-04/taobao_live_seller_agreement.html",
        "data/platform_rules/raw_html/2026-09-04/taobao_live_seller_agreement.headers.txt",
        notes=["平台服务协议，不等同于美妆行业专项审核细则。"],
    ),
    Source(
        "weibo_fans_headline_audit",
        "微博",
        "粉丝头条审核规范",
        "https://pay.biz.weibo.com/auditstandard",
        "data/platform_rules/raw_html/2026-09-04/weibo_fans_headline_audit.html",
        "data/platform_rules/raw_html/2026-09-04/weibo_fans_headline_audit.headers.txt",
    ),
    Source(
        "weibo_community_convention",
        "微博",
        "微博社区公约",
        "https://service.account.weibo.com/h5/roles/gongyue",
        "data/platform_rules/raw_html/2026-09-04/weibo_community_convention.html",
        "data/platform_rules/raw_html/2026-09-04/weibo_community_convention.headers.txt",
        notes=["社区商业行为规则，不等同于美妆行业专项投放规则。"],
    ),
    Source(
        "bilibili_huohua_pre_audit_general",
        "哔哩哔哩",
        "花火稿件前置审核规范总则",
        "https://www.bilibili.com/blackboard/activity-hp6i7WQHrx.html",
        "data/platform_rules/raw_html/2026-09-04/bilibili_huohua_pre_audit.html",
        "data/platform_rules/raw_html/2026-09-04/bilibili_huohua_pre_audit.headers.txt",
    ),
    Source(
        "bilibili_commercial_video_audit",
        "哔哩哔哩",
        "花火商单视频审核管理规范",
        "https://www.bilibili.com/blackboard/activity-QLKVrsgdYA.html",
        "data/platform_rules/raw_html/2026-09-04/bilibili_commercial_audit.html",
        "data/platform_rules/raw_html/2026-09-04/bilibili_commercial_audit.headers.txt",
    ),
    Source(
        "kuaishou_life_services_rule_2154",
        "快手",
        "快手生活服务广告内容管理规则（页面ID 2154）",
        "https://university.kuaishou.com/rule/knowledge/2154",
        "data/platform_rules/raw_html/2026-09-04/kuaishou_life_services_rules.html",
        "data/platform_rules/raw_html/2026-09-04/kuaishou_life_services_rules.headers.txt",
        notes=["下载HTML仅为动态页面外壳；且页面场景为生活服务，不能直接外推至快手电商美妆。"],
    ),
    Source(
        "tmall_merchant_service_agreement",
        "天猫",
        "天猫商户服务协议",
        "https://terms.alicdn.com/legal-agreement/terms/TD/TD201609271722_89275.html",
        "data/platform_rules/raw_html/2026-09-04/tmall_merchant_agreement.html",
        "data/platform_rules/raw_html/2026-09-04/tmall_merchant_agreement.headers.txt",
        notes=["平台服务协议，不等同于美妆行业专项审核细则。"],
    ),
    Source(
        "jd_open_platform_online_service_agreement",
        "京东",
        "京东JD.COM开放平台在线服务协议",
        "https://paipai-fe-cdn.s3.cn-north-1.jdcloud-oss.com/%E5%9C%A8%E7%BA%BF%E6%9C%8D%E5%8A%A1%E5%8D%8F%E8%AE%AE.pdf",
        "data/platform_rules/raw_files/2026-09-04/jd_open_platform_agreement.pdf",
        "data/platform_rules/raw_files/2026-09-04/jd_open_platform_agreement.headers.txt",
        capture_format="pdf",
        notes=["平台服务协议，不等同于京东美妆广告专项审核细则。"],
    ),
]


CLAUSE_CANDIDATES = [
    {
        "candidate_id": "XHS-JG-COSM-EFFECT-2.1.3",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.1.3 美妆",
        "rule_summary": "不得承诺起效时间或用量，不得过度保证安全性，不得承诺永久性效果。",
        "risk_dimensions": ["见效周期", "安全保证", "永久效果"],
    },
    {
        "candidate_id": "XHS-JG-PATENT-1.10",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—1.10",
        "rule_summary": "涉及专利产品或方法时，应提供有效专利证书并标明专利号和专利种类。",
        "risk_dimensions": ["专利证明"],
    },
    {
        "candidate_id": "XHS-JG-AD-ID-1.11",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—1.11",
        "rule_summary": "广告应具有可识别性，使消费者能够辨明其为广告。",
        "risk_dimensions": ["广告可识别性"],
    },
    {
        "candidate_id": "XHS-JG-ABSOLUTE-2.3",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.3",
        "rule_summary": "不得使用国家级、最高级、最佳、中国第一、顶级等绝对化用语。",
        "risk_dimensions": ["绝对化用语"],
    },
    {
        "candidate_id": "XHS-JG-DATA-2.8",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.8",
        "rule_summary": "数据、统计资料和调查结果应真实准确，标明出处、适用范围和有效期限，并提供证明。",
        "risk_dimensions": ["数据引证", "证明材料"],
    },
    {
        "candidate_id": "XHS-JG-MEDICAL-2.13",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.13",
        "rule_summary": "非药品、医疗器械、医疗机构物料不得涉及疾病治疗功能或医疗混淆用语。",
        "risk_dimensions": ["医疗用语", "疾病治疗"],
    },
    {
        "candidate_id": "XHS-JG-INGREDIENT-2.9",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.9",
        "rule_summary": "推广产品成分或材质时，应提供相应的成分或材质证明。",
        "risk_dimensions": ["成分证明", "材质证明"],
    },
    {
        "candidate_id": "XHS-JG-FACT-2.10",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.10",
        "rule_summary": "权威机构认证、临床验证等事实性表述应提供有效证明材料。",
        "risk_dimensions": ["事实性表述", "认证", "临床验证"],
    },
    {
        "candidate_id": "XHS-JG-ENDORSEMENT-2.11",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.11",
        "rule_summary": "不得利用第三方机构名义或形象宣传产品或服务。",
        "risk_dimensions": ["第三方机构背书"],
    },
    {
        "candidate_id": "XHS-JG-COMPARE-2.15",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—2.15",
        "rule_summary": "不得以虚假夸张的产品使用前后对比展示效果。",
        "risk_dimensions": ["前后对比", "效果夸大"],
    },
    {
        "candidate_id": "XHS-JG-CONSISTENCY-4.4",
        "source_id": "xhs_content_review_general_2026_03_23",
        "platform": "小红书",
        "locator": "三、通用素材审核要求—4.4",
        "rule_summary": "广告物料、实际展示、商品详情页以及品牌和产品信息应前后一致。",
        "risk_dimensions": ["物料一致性", "落地页一致性"],
    },
    {
        "candidate_id": "DOUYIN-COSM-EFFICACY-2.1.1",
        "source_id": "douyin_beauty_rules_notice_2022_05_10",
        "platform": "抖音电商",
        "locator": "二、禁止夸大、虚假宣传或描述—2.1.1",
        "rule_summary": "按注册备案功效范围宣传，不得宣称医疗、医美、保健功效或不存在的功效。",
        "risk_dimensions": ["超注册备案功效", "医疗功效"],
    },
    {
        "candidate_id": "DOUYIN-COSM-GUARANTEE-2.1.2",
        "source_id": "douyin_beauty_rules_notice_2022_05_10",
        "platform": "抖音电商",
        "locator": "二、禁止夸大、虚假宣传或描述—2.1.2",
        "rule_summary": "不得无依据保证效果或安全性；不得将化妆品宣传为可吃、可吞或食品级。",
        "risk_dimensions": ["效果保证", "可食用化妆品"],
    },
    {
        "candidate_id": "DOUYIN-COSM-PROOF-2.3",
        "source_id": "douyin_beauty_rules_notice_2022_05_10",
        "platform": "抖音电商",
        "locator": "二、禁止夸大、虚假宣传或描述—2.3",
        "rule_summary": "宣传专利、荣誉、销量、研发单位或效果指数时应展示相应证明。",
        "risk_dimensions": ["专利", "荣誉", "销量数据", "效果指数"],
    },
    {
        "candidate_id": "DOUYIN-COSM-ATTRIBUTE-2.4",
        "source_id": "douyin_beauty_rules_notice_2022_05_10",
        "platform": "抖音电商",
        "locator": "二、禁止夸大、虚假宣传或描述—2.4",
        "rule_summary": "成分、含量、产地和规格等信息应与实际商品及商品详情页一致。",
        "risk_dimensions": ["成分虚假", "商品信息不一致"],
    },
    {
        "candidate_id": "TENCENT-COSM-GENERAL-2",
        "source_id": "tencent_ads_skin_care_216",
        "platform": "腾讯广告",
        "locator": "（一）护肤彩妆广告通用审核规则—第2项",
        "rule_summary": "化妆品名称、制法、成分、效果或性能不得虚假夸大。",
        "risk_dimensions": ["虚假夸大", "成分", "功效"],
    },
    {
        "candidate_id": "TENCENT-COSM-MINOR-1",
        "source_id": "tencent_ads_skin_care_216",
        "platform": "腾讯广告",
        "locator": "（一）护肤彩妆广告通用审核规则—第1项",
        "rule_summary": "不得在针对未成年人的大众传播媒介发布化妆品、美容广告。",
        "risk_dimensions": ["未成年人媒介"],
    },
    {
        "candidate_id": "TENCENT-COSM-ENDORSEMENT-3",
        "source_id": "tencent_ads_skin_care_216",
        "platform": "腾讯广告",
        "locator": "（一）护肤彩妆广告通用审核规则—第3项",
        "rule_summary": "不得使用他人名义保证或以暗示方式使人误解产品效用。",
        "risk_dimensions": ["他人保证", "功效误导"],
    },
    {
        "candidate_id": "TENCENT-COSM-DATA-5",
        "source_id": "tencent_ads_skin_care_216",
        "platform": "腾讯广告",
        "locator": "（一）护肤彩妆广告通用审核规则—第5项",
        "rule_summary": "平台规则不支持涉及化妆品性能、功能或销量等方面的数据。",
        "risk_dimensions": ["功效数据", "销量数据"],
    },
    {
        "candidate_id": "TENCENT-COSM-COMPARE-8",
        "source_id": "tencent_ads_skin_care_216",
        "platform": "腾讯广告",
        "locator": "（一）护肤彩妆广告通用审核规则—第8项",
        "rule_summary": "素材不得使用病理图或使用前后效果对比图。",
        "risk_dimensions": ["病理图", "前后对比"],
    },
    {
        "candidate_id": "TENCENT-COSM-ABSOLUTE-6",
        "source_id": "tencent_ads_skin_care_216",
        "platform": "腾讯广告",
        "locator": "（一）护肤彩妆广告通用审核规则—第6项",
        "rule_summary": "不得使用最新创造、纯天然制品、无副作用等绝对化语言。",
        "risk_dimensions": ["绝对化用语", "安全保证"],
    },
    {
        "candidate_id": "TENCENT-COSM-QUALIFICATION-10",
        "source_id": "tencent_ads_skin_care_216",
        "platform": "腾讯广告",
        "locator": "（一）护肤彩妆广告通用审核规则—第10项",
        "rule_summary": "特殊用途化妆品资质中的产品名称应与实际推广商品一致。",
        "risk_dimensions": ["特殊化妆品资质", "产品一致性"],
    },
    {
        "candidate_id": "TAOBAO-LIVE-PUBLISH-3.3.1",
        "source_id": "taobao_live_seller_agreement_20220516174444172",
        "platform": "淘宝直播",
        "locator": "3.3.1 商品及/或服务信息发布",
        "rule_summary": "发布信息和经营行为应符合法律法规、强制性标准及协议约定，违规信息应及时删除。",
        "risk_dimensions": ["信息发布合规", "违法信息处置"],
    },
    {
        "candidate_id": "TAOBAO-LIVE-INFO-3.3.2",
        "source_id": "taobao_live_seller_agreement_20220516174444172",
        "platform": "淘宝直播",
        "locator": "3.3.2—第（一）、（三）项",
        "rule_summary": "不得发布违反法律禁止性规定或欺诈、虚假、不准确、误导性的信息。",
        "risk_dimensions": ["违法信息", "虚假误导"],
    },
    {
        "candidate_id": "WEIBO-AUDIT-COSM-SECTION-2",
        "source_id": "weibo_fans_headline_audit",
        "platform": "微博",
        "locator": "二、审核规则",
        "rule_summary": "推广内容应遵守广告法及化妆品等特殊领域广告管理规定。",
        "risk_dimensions": ["法律法规转介"],
    },
    {
        "candidate_id": "WEIBO-COMMERCIAL-37-40",
        "source_id": "weibo_community_convention",
        "platform": "微博",
        "locator": "第八章商业行为规则—第37至40条",
        "rule_summary": "微博商业广告受平台审查；未通过商业渠道且缺乏广告可识别性的营销信息可被限制。",
        "risk_dimensions": ["广告可识别性", "商业渠道"],
    },
    {
        "candidate_id": "WEIBO-AUDIT-CONTENT-IV-2",
        "source_id": "weibo_fans_headline_audit",
        "platform": "微博",
        "locator": "四、推广审核规范—2.推广审核要点—内容",
        "rule_summary": "推广内容不得使用绝对化用语或国家机关背书；化妆品推广不得使用医疗术语或治疗性表述。",
        "risk_dimensions": ["绝对化用语", "国家机关背书", "医疗用语"],
    },
    {
        "candidate_id": "BILI-HUOHUA-ABSOLUTE-II",
        "source_id": "bilibili_huohua_pre_audit_general",
        "platform": "哔哩哔哩",
        "locator": "二、绝对化（用语）",
        "rule_summary": "商推内容不得使用广告法明令禁止的绝对词；其他绝对化表述应提供相符佐证。",
        "risk_dimensions": ["绝对化用语", "证明材料"],
    },
    {
        "candidate_id": "BILI-HUOHUA-PATENT-III",
        "source_id": "bilibili_huohua_pre_audit_general",
        "platform": "哔哩哔哩",
        "locator": "三、专利数据类",
        "rule_summary": "专利应标注专利号；功效数据尤其接近99%至100%的数据，应提供匹配的第三方报告。",
        "risk_dimensions": ["专利", "功效数据"],
    },
    {
        "candidate_id": "BILI-HUOHUA-MEDICAL-IV-2",
        "source_id": "bilibili_huohua_pre_audit_general",
        "platform": "哔哩哔哩",
        "locator": "四、高风险行业—2.医疗用语",
        "rule_summary": "非医疗类推广不得使用疾病诊疗、注射、消炎、抗炎等医疗用语。",
        "risk_dimensions": ["医疗用语", "疾病治疗"],
    },
    {
        "candidate_id": "BILI-HUOHUA-COMPARE-VIII",
        "source_id": "bilibili_huohua_pre_audit_general",
        "platform": "哔哩哔哩",
        "locator": "八、诱导类",
        "rule_summary": "化妆品前后效果对比图和病理图存在误导风险，应避免使用。",
        "risk_dimensions": ["前后对比", "病理图"],
    },
]


EVIDENCE_EXCERPTS = {
    "XHS-JG-COSM-EFFECT-2.1.3": "不得涉及承诺产品起效的时间或用量；不得过度承诺产品的安全性；不得涉及永久性效果承诺。",
    "XHS-JG-PATENT-1.10": "涉及专利产品或者专利方法的，需提供真实有效的专利证书，并在素材中标明专利号、专利种类。",
    "XHS-JG-AD-ID-1.11": "广告应当具有可识别性，能够使消费者辨明其为广告。",
    "XHS-JG-ABSOLUTE-2.3": "不得涉及国家级、最高级、最佳、中国第一、顶级等绝对化用语。",
    "XHS-JG-DATA-2.8": "引证内容应当真实、准确并表明出处；有适用范围和有效期限的应当明确表示，同时提供证明材料。",
    "XHS-JG-MEDICAL-2.13": "除药品、医疗器械、医疗机构物料外，其他物料不得涉及疾病治疗功能或使用医疗混淆用语。",
    "XHS-JG-INGREDIENT-2.9": "物料内容中所推广的产品成分或材质，需提供对应的成分、材质证明。",
    "XHS-JG-FACT-2.10": "物料涉及事实性表述，需提供有效的证明材料做佐证。",
    "XHS-JG-ENDORSEMENT-2.11": "物料不得利用第三方机构名义或形象进行产品或服务宣传。",
    "XHS-JG-COMPARE-2.15": "物料不得涉及产品的前后使用效果做虚假夸张的对比描述。",
    "XHS-JG-CONSISTENCY-4.4": "物料推广内容前后需保持一致，涉及品牌、产品的内容需与商品详情页保持一致。",
    "DOUYIN-COSM-EFFICACY-2.1.1": "推广化妆品类商品时，需严格按照商品注册、备案的功效范围宣传。",
    "DOUYIN-COSM-GUARANTEE-2.1.2": "禁止在无依据、无证明的情况下，对未来功效、效果、安全性作出保证性承诺。",
    "DOUYIN-COSM-PROOF-2.3": "宣传专利、荣誉、销量、权威研发单位、效果指数等信息时，需展示相关证明材料。",
    "DOUYIN-COSM-ATTRIBUTE-2.4": "应确保化妆品成分、含量、产地、规格等描述与商品详情页或实际商品保持一致。",
    "TENCENT-COSM-GENERAL-2": "化妆品名称、制法、成分、效果或者性能不得有虚假夸大。",
    "TENCENT-COSM-MINOR-1": "在针对未成年人的大众传播媒介上不得发布化妆品、美容广告。",
    "TENCENT-COSM-ENDORSEMENT-3": "不得使用他人名义保证或者以暗示方法使人误解其效用。",
    "TENCENT-COSM-DATA-5": "不得涉及化妆品性能或者功能、销量等方面的数据。",
    "TENCENT-COSM-COMPARE-8": "素材形象不得使用病理图，图片不得有使用前后的效果对比。",
    "TENCENT-COSM-ABSOLUTE-6": "不得使用最新创造、最新发明、纯天然制品、无副作用等绝对化语言。",
    "TENCENT-COSM-QUALIFICATION-10": "特殊用途化妆品资质中的产品名称与实际推广商品需保持一致。",
    "TAOBAO-LIVE-PUBLISH-3.3.1": "发布的信息及实施的行为应符合法律法规、国家强制性标准及协议约定。",
    "TAOBAO-LIVE-INFO-3.3.2": "禁止发布违反国家法律法规禁止性规定，或者欺诈、虚假、不准确、存在误导性的信息。",
    "WEIBO-AUDIT-COSM-SECTION-2": "推广内容应严格遵守国家相关法律法规以及化妆品等特殊领域产品的广告管理规定。",
    "WEIBO-COMMERCIAL-37-40": "未通过商业产品渠道且不具有互联网广告可识别性的营销信息，平台可采取屏蔽、限制展示等措施。",
    "WEIBO-AUDIT-CONTENT-IV-2": "涉及化妆品的推广内容不得使用医疗术语以及明示或暗示有治疗作用的词语。",
    "BILI-HUOHUA-ABSOLUTE-II": "商推部分禁止使用国家级、最高级、最佳等绝对词关联产品推广。",
    "BILI-HUOHUA-PATENT-III": "涉及产品功效的具体数据类内容，应提供对应的数据证明。",
    "BILI-HUOHUA-MEDICAL-IV-2": "非三品一械稿件中禁止使用医疗类用语进行产品推广。",
    "BILI-HUOHUA-COMPARE-VIII": "使用前后对比图及病理图容易形成误导，规则提示应尽量避免使用。",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_headers(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    statuses = re.findall(r"^HTTP/\S+\s+(\d{3})", text, flags=re.MULTILINE | re.IGNORECASE)
    content_types = re.findall(r"^content-type:\s*(.+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    return {
        "http_status_chain": [int(value) for value in statuses],
        "final_http_status": int(statuses[-1]) if statuses else None,
        "content_type": content_types[-1].strip() if content_types else None,
    }


def extract_html(path: Path) -> str:
    html = path.read_text(encoding="utf-8", errors="replace")
    parser = VisibleTextExtractor()
    parser.feed(html)
    visible_text = "\n".join(parser.parts)

    # Bilibili activity pages server-render their rule body into a JSON object
    # inside a script tag.  Preserve that public body without executing scripts.
    state_match = re.search(
        r"window\.__initialState\s*=\s*(\{.*?\});\s*\n\s*window\.__BILIACT_MODULES__",
        html,
        flags=re.DOTALL,
    )
    if state_match:
        state = json.loads(state_match.group(1))
        rich_fragments: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "dangerHtml" and isinstance(child, str):
                        rich_fragments.append(child)
                    else:
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(state)
        if rich_fragments:
            rich_parser = VisibleTextExtractor()
            rich_parser.feed("\n".join(rich_fragments))
            rendered_text = "\n".join(rich_parser.parts)
            if len(rendered_text) > len(visible_text):
                return rendered_text
    return visible_text


def extract_pdf(path: Path) -> str:
    command = ["/opt/homebrew/bin/pdftotext", "-layout", str(path), "-"]
    completed = subprocess.run(command, check=True, capture_output=True)
    return completed.stdout.decode("utf-8", errors="replace").strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection-date", default="2026-09-04")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / "data/platform_rules/raw_text" / args.collection_date
    candidate_dir = PROJECT_ROOT / "data/platform_rules/structured_candidates" / args.collection_date
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    records: list[dict[str, Any]] = []
    for source in SOURCES:
        raw_path = PROJECT_ROOT / source.raw_path
        headers_path = PROJECT_ROOT / source.headers_path
        if not raw_path.exists():
            raise FileNotFoundError(raw_path)
        text = extract_pdf(raw_path) if source.capture_format == "pdf" else extract_html(raw_path)
        text_path = output_dir / f"{source.source_id}.json"
        dynamic_shell = len(text) < 500
        payload = {
            "source_id": source.source_id,
            "platform": source.platform,
            "document_title": source.document_title,
            "source_url": source.url,
            "manual_verification_url": source.url,
            "collected_at": collected_at,
            "page_update_date": source.page_update_date,
            "capture_format": source.capture_format,
            "capture_method": "direct_public_download_no_login",
            "raw_path": source.raw_path,
            "raw_headers_path": source.headers_path,
            "raw_sha256": sha256(raw_path),
            "raw_size_bytes": raw_path.stat().st_size,
            "extracted_text": text,
            "verified_visible_excerpts": [
                {
                    "candidate_id": item["candidate_id"],
                    "locator": item["locator"],
                    "text": EVIDENCE_EXCERPTS[item["candidate_id"]],
                }
                for item in CLAUSE_CANDIDATES
                if item["source_id"] == source.source_id
            ],
            "extracted_text_length": len(text),
            "snapshot_completeness": "dynamic_html_shell_only" if dynamic_shell else "downloaded_page_text_extracted",
            "robots_and_access_note": "仅直接下载无需登录的公开页面，未绕过验证码、登录、robots.txt或非公开接口。",
            "copyright_note": "原始快照仅用于内部合规溯源与人工核验，不作为对外发布版本。",
            "review_status": "pending_human_review",
            "effective_status": "pending_effective_review",
            "intended_use": source.intended_use,
            "notes": source.notes,
            **parse_headers(headers_path),
        }
        text_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append({key: value for key, value in payload.items() if key != "extracted_text"} | {
            "raw_text_path": str(text_path.relative_to(PROJECT_ROOT))
        })

    source_ids = {record["source_id"] for record in records}
    candidates = []
    for item in CLAUSE_CANDIDATES:
        if item["source_id"] not in source_ids:
            raise ValueError(f"unknown source_id: {item['source_id']}")
        source_record = next(record for record in records if record["source_id"] == item["source_id"])
        candidates.append(
            {
                **item,
                "document_title": source_record["document_title"],
                "source_url": source_record["source_url"],
                "manual_verification_url": source_record["manual_verification_url"],
                "raw_text_path": source_record["raw_text_path"],
                "raw_sha256": source_record["raw_sha256"],
                "evidence_excerpt": EVIDENCE_EXCERPTS[item["candidate_id"]],
                "evidence_excerpt_type": "short_visible_text_excerpt",
                "retrieval_text": (
                    f"{item['platform']}平台的{source_record['document_title']}针对"
                    f"{'、'.join(item['risk_dimensions'])}作出审核要求：{item['rule_summary']}"
                    "该规则仅用于平台审核预检，不能替代法律结论或平台最终审核。"
                ),
                "effective_status": "pending_effective_review",
                "review_status": "pending_legal_review",
                "release_eligibility": "candidate_only",
                "human_review_required": True,
            }
        )

    manifest = {
        "manifest_id": f"beauty_platform_rule_sources_{args.collection_date.replace('-', '_')}",
        "collected_at": collected_at,
        "catalog_status": "candidate_only_not_for_production",
        "source_count": len(records),
        "sources": records,
        "release_gate": "规则正文、版本、生效状态和适用场景经平台运营与法务双人复核后，方可进入正式规则库。",
    }
    catalog = {
        "catalog_id": f"beauty_platform_rule_candidates_{args.collection_date.replace('-', '_')}",
        "created_at": collected_at,
        "catalog_status": "candidate_only_not_for_production",
        "candidate_count": len(candidates),
        "rules": candidates,
    }
    (PROJECT_ROOT / f"data/platform_rules/manifest_{args.collection_date}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (candidate_dir / "beauty_platform_rule_candidates.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    candidate_counts: dict[str, int] = {}
    for candidate in candidates:
        candidate_counts[candidate["source_id"]] = candidate_counts.get(candidate["source_id"], 0) + 1
    markdown = [
        "# 平台规则人工核验清单（2026-09-04）",
        "",
        "> 本批次均为候选资料，尚未进入生产规则库。人工核验时应确认页面标题、版本或更新时间、适用场景、条款定位和当前有效状态。",
        "",
        "| 平台 | 文件 | 候选条款 | 快照完整性 | 官方人工核验链接 | 本地原始快照 | 本地文本 |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for record in records:
        raw_link = Path(record["raw_path"]).relative_to("data/platform_rules").as_posix()
        text_link = Path(record["raw_text_path"]).relative_to("data/platform_rules").as_posix()
        markdown.append(
            "| {platform} | {title} | {count} | `{completeness}` | [打开官方页面]({url}) | "
            "[{raw_label}]({raw_link}) | [{text_label}]({text_link}) |".format(
                platform=record["platform"],
                title=record["document_title"].replace("|", "\\|"),
                count=candidate_counts.get(record["source_id"], 0),
                completeness=record["snapshot_completeness"],
                url=record["manual_verification_url"],
                raw_label=record["raw_path"],
                raw_link=raw_link,
                text_label=record["raw_text_path"],
                text_link=text_link,
            )
        )
    markdown.extend(
        [
            "",
            "## 放行门槛",
            "",
            "1. `dynamic_html_shell_only` 页面必须在浏览器中逐条核对候选摘录，不能仅凭下载HTML放行。",
            "2. 服务协议不能替代美妆行业专项投放规则；天猫、京东、快手当前只作来源候选。",
            "3. 复核通过后，将 `review_status` 改为 `approved`，并单独确认 `effective_status=active`。",
            "4. 平台规则命中只产生平台审核风险，不自动生成行政违法结论。",
            "",
        ]
    )
    (PROJECT_ROOT / f"data/platform_rules/manual_verification_{args.collection_date}.md").write_text(
        "\n".join(markdown), encoding="utf-8"
    )
    print(json.dumps({"sources": len(records), "candidates": len(candidates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
