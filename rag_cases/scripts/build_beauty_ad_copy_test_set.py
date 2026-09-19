#!/usr/bin/env python3
"""按保健食品队友模板生成美妆广告文案测试集。

输出保留模板的 test_set_id/name/version/purpose/input_contract/cases 结构，
并在 expected 中增加可供人工核验的法律条文、平台规则定位和官方链接。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_CATALOG = (
    ROOT
    / "data/platform_rules/structured_candidates/2026-09-04/beauty_platform_rule_candidates.json"
)
OUTPUT = ROOT / "data/audit_test_cases/beauty_ad_copy_test_set_20260908.json"

ADVERTISING_LAW_URL = (
    "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/"
    "art_5474cf75173c45d6a0379730fb4e8d97.html"
)
COSMETICS_REGULATION_URL = "https://xzfg.moj.gov.cn/front/law/detail?LawID=451"
INTERNET_AD_URL = (
    "https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/"
    "art_d93a579afd45413e8576e4623fab348f.html"
)
EFFICACY_NMPA_URL = "https://english.nmpa.gov.cn/2021-04/09/c_654820.htm"
EFFICACY_FULL_TEXT_MIRROR = "https://vip.caffci.org/content/details_14_476.html"
CHILD_COSMETICS_URL = (
    "https://scjgj.beijing.gov.cn/zwxx/scjgdt/202310/"
    "t20231018_3281369.html"
)


LEGAL: dict[str, dict[str, Any]] = {
    "ADLAW-004": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第四条",
        "provision_text": "广告不得含有虚假或者引人误解的内容，不得欺骗、误导消费者。广告主应当对广告内容的真实性负责。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "ADLAW-008": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第八条",
        "provision_text": "广告中对商品的性能、功能、产地、用途、质量、成分、价格、生产者、有效期限、允诺等或者对服务的内容、提供者、形式、质量、价格、允诺等有表示的，应当准确、清楚、明白。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "ADLAW-009-03": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第九条第（三）项",
        "provision_text": "广告不得使用“国家级”、“最高级”、“最佳”等用语。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "ADLAW-011-02": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第十一条第二款",
        "provision_text": "广告使用数据、统计资料、调查结果、文摘、引用语等引证内容的，应当真实、准确，并表明出处。引证内容有适用范围和有效期限的，应当明确表示。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "ADLAW-012-01": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第十二条第一款",
        "provision_text": "广告中涉及专利产品或者专利方法的，应当标明专利号和专利种类。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "ADLAW-017": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第十七条",
        "provision_text": "除医疗、药品、医疗器械广告外，禁止其他任何广告涉及疾病治疗功能，并不得使用医疗用语或者易使推销的商品与药品、医疗器械相混淆的用语。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "ADLAW-028": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第二十八条第一款及第二款第（二）至（四）项",
        "provision_text": "广告以虚假或者引人误解的内容欺骗、误导消费者的，构成虚假广告。广告有下列情形之一的，为虚假广告：（二）商品的性能、功能、产地、用途、质量、规格、成分、价格、生产者、有效期限、销售状况、曾获荣誉等信息，或者服务的内容、提供者、形式、质量、价格、销售状况、曾获荣誉等信息，以及与商品或者服务有关的允诺等信息与实际情况不符，对购买行为有实质性影响的；（三）使用虚构、伪造或者无法验证的科研成果、统计资料、调查结果、文摘、引用语等信息作证明材料的；（四）虚构使用商品或者接受服务的效果的。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "ADLAW-038-01": {
        "document_title": "《中华人民共和国广告法》",
        "article": "第三十八条第一款",
        "provision_text": "广告代言人在广告中对商品、服务作推荐、证明，应当依据事实，符合本法和有关法律、行政法规规定，并不得为其未使用过的商品或者未接受过的服务作推荐、证明。",
        "source_url": ADVERTISING_LAW_URL,
    },
    "COSM-REG-016": {
        "document_title": "《化妆品监督管理条例》",
        "article": "第十六条",
        "provision_text": "用于染发、烫发、祛斑美白、防晒、防脱发的化妆品以及宣称新功效的化妆品为特殊化妆品。特殊化妆品以外的化妆品为普通化妆品。",
        "source_url": COSMETICS_REGULATION_URL,
    },
    "COSM-REG-017": {
        "document_title": "《化妆品监督管理条例》",
        "article": "第十七条",
        "provision_text": "特殊化妆品经国务院药品监督管理部门注册后方可生产、进口。国产普通化妆品应当在上市销售前向备案人所在地省、自治区、直辖市人民政府药品监督管理部门备案。进口普通化妆品应当在进口前向国务院药品监督管理部门备案。",
        "source_url": COSMETICS_REGULATION_URL,
    },
    "COSM-REG-022": {
        "document_title": "《化妆品监督管理条例》",
        "article": "第二十二条",
        "provision_text": "化妆品的功效宣称应当有充分的科学依据。化妆品注册人、备案人应当在国务院药品监督管理部门规定的专门网站公布功效宣称所依据的文献资料、研究数据或者产品功效评价资料的摘要，接受社会监督。",
        "source_url": COSMETICS_REGULATION_URL,
    },
    "COSM-REG-043": {
        "document_title": "《化妆品监督管理条例》",
        "article": "第四十三条",
        "provision_text": "化妆品广告的内容应当真实、合法。化妆品广告不得明示或者暗示产品具有医疗作用，不得含有虚假或者引人误解的内容，不得欺骗、误导消费者。",
        "source_url": COSMETICS_REGULATION_URL,
    },
    "COSM-EVAL-009": {
        "document_title": "《化妆品功效宣称评价规范》",
        "article": "第九条",
        "provision_text": "具有抗皱、紧致、舒缓、控油、去角质、防断发和去屑功效，以及宣称温和（如无刺激）或量化指标（如功效宣称保持时间、功效宣称相关统计数据等）的化妆品，应当通过化妆品功效宣称评价试验方式，可以同时结合文献资料或研究数据分析结果，进行功效宣称评价。",
        "source_url": EFFICACY_NMPA_URL,
        "manual_verification_url": EFFICACY_FULL_TEXT_MIRROR,
    },
    "COSM-EVAL-010": {
        "document_title": "《化妆品功效宣称评价规范》",
        "article": "第十条",
        "provision_text": "具有祛斑美白、防晒、防脱发、祛痘、滋养和修护功效的化妆品，应当通过人体功效评价试验方式进行功效宣称评价。",
        "source_url": EFFICACY_NMPA_URL,
        "manual_verification_url": EFFICACY_FULL_TEXT_MIRROR,
    },
    "CHILD-COSM-013": {
        "document_title": "《儿童化妆品监督管理规定》",
        "article": "第十三条第二款",
        "provision_text": "儿童化妆品标签不得标注“食品级”“可食用”等词语或者食品有关图案。",
        "source_url": CHILD_COSMETICS_URL,
    },
    "INET-AD-009-03": {
        "document_title": "《互联网广告管理办法》",
        "article": "第九条第三款",
        "provision_text": "通过知识介绍、体验分享、消费测评等形式推销商品或者服务，并附加购物链接等购买方式的，广告发布者应当显著标明“广告”。",
        "source_url": INTERNET_AD_URL,
    },
}


def load_platform_rules() -> dict[str, dict[str, Any]]:
    payload = json.loads(PLATFORM_CATALOG.read_text(encoding="utf-8"))
    return {item["candidate_id"]: item for item in payload["rules"]}


PLATFORM = load_platform_rules()


def legal(rule_id: str, application: str, *, expected_hit: bool = True) -> dict[str, Any]:
    item = deepcopy(LEGAL[rule_id])
    item.update(
        {
            "rule_id": rule_id,
            "application": application,
            "expected_hit": expected_hit,
            "verification_status": "official_source_checked_2026-09-08",
        }
    )
    return item


def platform(
    rule_id: str,
    application: str,
    *,
    expected_hit: bool = True,
) -> dict[str, Any]:
    source = PLATFORM[rule_id]
    return {
        "rule_id": rule_id,
        "platform": source["platform"],
        "document_title": source["document_title"],
        "locator": source["locator"],
        "provision_text": source["evidence_excerpt"],
        "application": application,
        "expected_hit": expected_hit,
        "source_url": source["source_url"],
        "snapshot_collected_at": "2026-09-04",
        "raw_text_path": source["raw_text_path"],
        "review_status": source["review_status"],
        "effective_status": source["effective_status"],
        "human_review_required": True,
    }


def fields(
    case_no: int,
    content: str,
    platforms: list[str],
    *,
    supplement: str,
    material_type: str = "图文",
    product_category: str = "护肤",
    scene: str,
    claims: str | list[str],
    filing_name: str = "",
    urgency: str = "普通",
) -> dict[str, Any]:
    return {
        "record_id": f"rec_beauty_ad_{case_no:03d}",
        "mode": "标准",
        "fields": {
            "①运营·行业领域": "美妆",
            "①运营·物料内容": content,
            "①运营·紧急程度": urgency,
            "①运营·补充背景资料": supplement,
            "①美妆·物料类型": material_type,
            "①美妆·投放平台": platforms,
            "①美妆·产品品类": product_category,
            "①美妆·物料涉及场景": scene,
            "①美妆·核心宣称功效": claims,
            "①美妆·产品备案名称": filing_name,
        },
    }


def expected(
    judgment: str,
    must_recall: list[str],
    suspected: list[str],
    legal_rules: list[dict[str, Any]],
    platform_rules: list[dict[str, Any]],
    evidence: list[str],
    action: str,
    *,
    must_not_recall: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "expected_judgment": judgment,
        "expected_routing": "运营",
        "must_recall_rule_ids": must_recall,
        "suspected_legal_basis": suspected,
        "legal_provisions": legal_rules,
        "platform_provisions": platform_rules,
        "evidence_requirements": evidence,
        "recommended_action": action,
        "human_review_required": True,
        "reference_answer_status": "candidate_pending_human_review",
        "decision_boundary": "仅为测试期望和平台预检参考，不构成行政违法认定，也不代表平台必然审核通过或驳回。",
    }
    if must_not_recall is not None:
        result["must_not_recall_rule_ids"] = must_not_recall
    return result


def build_cases() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "BEAUTY-AD-001",
            "name": "化妆品医疗用语",
            "label": "疑似违规",
            "test_focus": ["医疗用语", "疾病治疗功能", "微信投放范围"],
            "input_payload": fields(
                1,
                "可杀菌、消炎、镇痛",
                ["微信"],
                supplement="未提供医疗器械注册证或能证明产品属性的备案资料；拟用于公众号、手册和挂纸宣传。",
                product_category="其他",
                scene="公众号、手册和挂纸宣传",
                claims=["杀菌", "消炎", "镇痛"],
            ),
            "expected": expected(
                "违规修改",
                ["ADLAW-017", "ADLAW-028", "TENCENT-COSM-GENERAL-2"],
                [
                    "【法律】《中华人民共和国广告法》第十七条、第二十八条",
                    "【行政法规】《化妆品监督管理条例》第四十三条",
                    "【平台规则】腾讯广告《护肤彩妆》通用审核规则第2项（仅适用经腾讯广告投放的微信流量）",
                ],
                [
                    legal("ADLAW-017", "“杀菌、消炎、镇痛”易被理解为医疗用语或疾病治疗功能。"),
                    legal("ADLAW-028", "若产品无相应属性或功效依据，可能构成虚假或引人误解广告。"),
                    legal("COSM-REG-043", "化妆品广告不得明示或暗示医疗作用。"),
                ],
                [platform("TENCENT-COSM-GENERAL-2", "功效表述存在虚假夸大风险；本条仅适用腾讯广告付费投放场景。")],
                ["产品注册/备案信息", "产品法律属性", "功效宣称评价资料", "微信内具体投放产品及场景"],
                "删除“杀菌、消炎、镇痛”等医疗化表述；确认产品属性和投放场景后再审核。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-002",
            "name": "B站商单绝对化宣称",
            "label": "疑似违规",
            "test_focus": ["绝对化用语", "国家级", "B站花火"],
            "input_payload": fields(
                2,
                "国家级抗老科技，全网效果最佳，顶级面霜。",
                ["b站"],
                supplement="商单视频，未提供评比范围、权威评比文件或数据依据。",
                material_type="短视频",
                scene="B站花火商单视频",
                claims=["国家级", "效果最佳", "顶级"],
                filing_name="光采抗皱面霜",
            ),
            "expected": expected(
                "违规修改",
                ["ADLAW-009-03", "BILI-HUOHUA-ABSOLUTE-II"],
                [
                    "【法律】《中华人民共和国广告法》第九条第（三）项",
                    "【平台规则】哔哩哔哩《花火稿件前置审核规范总则》二、绝对化（用语）",
                ],
                [legal("ADLAW-009-03", "文案直接使用“国家级”“最佳”等用语，并以“顶级”指向产品。")],
                [platform("BILI-HUOHUA-ABSOLUTE-II", "商推内容使用平台明确列举的绝对化用语。")],
                ["完整视频及封面", "与“全网效果最佳”相关的评比范围和证明材料"],
                "删除“国家级”“最佳”“顶级”，改为与备案和功效评价一致的客观描述。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-003",
            "name": "小红书七天美白与99%数据",
            "label": "疑似违规",
            "test_focus": ["见效周期", "量化数据", "永久效果"],
            "input_payload": fields(
                3,
                "7天美白3个度，99%用户见效，一次祛斑永不反弹。",
                ["小红书"],
                supplement="品牌种草图文，附购物链接；未提供人体功效评价报告、样本量、统计口径和摘要公布链接。",
                scene="聚光图文种草",
                claims=["7天美白", "99%见效", "永不反弹"],
                filing_name="美白祛斑精华液",
            ),
            "expected": expected(
                "违规修改",
                ["ADLAW-011-02", "ADLAW-028", "XHS-JG-COSM-EFFECT-2.1.3", "XHS-JG-DATA-2.8"],
                [
                    "【法律】《中华人民共和国广告法》第十一条第二款、第二十八条",
                    "【行政法规】《化妆品监督管理条例》第二十二条、第四十三条",
                    "【规范性文件】《化妆品功效宣称评价规范》第九条、第十条",
                    "【平台规则】小红书《内容审核规则总则》三、通用素材审核要求—2.1.3美妆、2.8",
                ],
                [
                    legal("ADLAW-011-02", "“99%”属于引证数据，应当真实、准确并表明出处。"),
                    legal("ADLAW-028", "不可验证的数据、虚构效果或与实际不符的功效可构成虚假广告。"),
                    legal("COSM-REG-022", "美白、祛斑功效宣称须有充分科学依据并公布摘要。"),
                    legal("COSM-REG-043", "永久性效果承诺可能虚假或引人误解。"),
                    legal("COSM-EVAL-009", "“7天”和“99%”属量化指标，应进行功效宣称评价试验。"),
                    legal("COSM-EVAL-010", "祛斑美白宣称应通过人体功效评价试验。"),
                ],
                [
                    platform("XHS-JG-COSM-EFFECT-2.1.3", "命中起效时间及永久效果承诺。"),
                    platform("XHS-JG-DATA-2.8", "“99%”未标明出处、适用范围和有效期限。"),
                ],
                ["特殊化妆品注册证", "人体功效评价报告", "“99%”的原始数据、样本及统计口径", "功效宣称依据摘要公布页"],
                "删除“7天”“99%”“永不反弹”等无法充分证明或平台明确限制的表述。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-004",
            "name": "普通化妆品超备案功效",
            "label": "疑似违规",
            "test_focus": ["特殊化妆品", "超注册备案功效", "抖音美妆"],
            "input_payload": fields(
                4,
                "普通精华也能祛斑美白、防晒、防脱发，一瓶解决所有问题。",
                ["抖音"],
                supplement="备案资料显示为普通化妆品，备案功效仅为保湿。",
                material_type="短视频",
                scene="抖音电商短视频",
                claims=["祛斑美白", "防晒", "防脱发"],
                filing_name="水光保湿精华液",
            ),
            "expected": expected(
                "违规修改",
                ["ADLAW-028", "DOUYIN-COSM-EFFICACY-2.1.1"],
                [
                    "【法律】《中华人民共和国广告法》第二十八条",
                    "【行政法规】《化妆品监督管理条例》第十六条、第十七条、第四十三条",
                    "【平台规则】抖音电商《关于〈美妆行业宣传规范〉修订的公示通知》二、禁止夸大、虚假宣传或描述—2.1.1",
                ],
                [
                    legal("ADLAW-028", "宣传功能与普通化妆品备案功效不符。"),
                    legal("COSM-REG-016", "祛斑美白、防晒和防脱发属于特殊化妆品功效范围。"),
                    legal("COSM-REG-017", "特殊化妆品应当注册后方可生产、进口。"),
                    legal("COSM-REG-043", "超出备案功效的宣传容易虚假或引人误解。"),
                ],
                [platform("DOUYIN-COSM-EFFICACY-2.1.1", "文案超出产品注册、备案的功效范围。")],
                ["完整注册/备案凭证", "实际商品标签", "功效宣称依据摘要"],
                "删除祛斑美白、防晒、防脱发宣称，仅保留与实际备案一致的保湿表述。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-005",
            "name": "儿童化妆品可食用宣称",
            "label": "疑似违规",
            "test_focus": ["儿童化妆品", "食品级", "安全性保证"],
            "input_payload": fields(
                5,
                "食品级儿童润唇膏，宝宝可以放心吃，100%无任何风险。",
                ["抖音"],
                supplement="儿童化妆品直播话术，未提供安全评估资料。",
                material_type="直播话术",
                product_category="唇部护理",
                scene="抖音电商直播",
                claims=["食品级", "可食用", "100%无风险"],
                filing_name="童趣润唇膏",
            ),
            "expected": expected(
                "违规修改",
                ["DOUYIN-COSM-GUARANTEE-2.1.2"],
                [
                    "【监管规定】《儿童化妆品监督管理规定》第十三条",
                    "【行政法规】《化妆品监督管理条例》第四十三条",
                    "【平台规则】抖音电商《关于〈美妆行业宣传规范〉修订的公示通知》二、禁止夸大、虚假宣传或描述—2.1.2",
                ],
                [
                    legal("CHILD-COSM-013", "“食品级”“可以放心吃”与儿童化妆品禁止性标签要求直接冲突。"),
                    legal("COSM-REG-043", "“100%无任何风险”是容易误导的安全性绝对保证。"),
                ],
                [platform("DOUYIN-COSM-GUARANTEE-2.1.2", "同时命中无依据安全性保证及化妆品可吃、可吞表述。")],
                ["儿童化妆品备案信息", "安全评估资料", "产品标签全图", "直播完整上下文"],
                "删除“食品级”“可吃”和“100%无风险”，改为标签允许的客观用途说明。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-006",
            "name": "医生推荐与临床数据",
            "label": "疑似违规/需补资料",
            "test_focus": ["医生推荐", "临床验证", "99%有效"],
            "input_payload": fields(
                6,
                "三甲医院皮肤科医生亲测推荐，临床验证99%有效。",
                ["微信"],
                supplement="腾讯广告信息流素材；未提供医生身份、书面授权、实际使用证明或试验报告。",
                scene="微信朋友圈信息流广告",
                claims=["医生推荐", "临床验证", "99%有效"],
                filing_name="舒缓修护面霜",
            ),
            "expected": expected(
                "需补资料",
                ["ADLAW-011-02", "ADLAW-028", "TENCENT-COSM-ENDORSEMENT-3", "TENCENT-COSM-DATA-5"],
                [
                    "【法律】《中华人民共和国广告法》第十一条第二款、第二十八条、第三十八条第一款",
                    "【行政法规】《化妆品监督管理条例》第二十二条、第四十三条",
                    "【平台规则】腾讯广告《护肤彩妆》通用审核规则第3项、第5项",
                ],
                [
                    legal("ADLAW-011-02", "临床验证和99%数据需真实、准确并标明出处。"),
                    legal("ADLAW-028", "若医生、医院或试验数据系虚构或无法验证，可构成虚假广告。"),
                    legal("ADLAW-038-01", "以个人名义或形象作推荐、证明时，应依据事实且实际使用过商品。"),
                    legal("COSM-REG-022", "功效数据应有充分科学依据。"),
                    legal("COSM-REG-043", "医院和医生表述还可能强化医疗作用暗示。"),
                ],
                [
                    platform("TENCENT-COSM-ENDORSEMENT-3", "未证明的他人名义保证可使人误解产品效用。"),
                    platform("TENCENT-COSM-DATA-5", "素材直接使用化妆品功效数据，命中平台限制。"),
                ],
                ["医生真实身份及书面授权", "实际使用证明", "临床试验完整报告", "统计口径、样本量和适用范围", "功效摘要公布链接"],
                "材料未补齐前不投放；即使材料真实，仍须按腾讯广告更严的平台规则删改背书和功效数据。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-007",
            "name": "B站前后效果对比",
            "label": "疑似违规",
            "test_focus": ["使用前后对比", "效果误导", "病理图"],
            "input_payload": fields(
                7,
                "左图烂脸长痘，右图用完一瓶皮肤完美无瑕，效果如图所见。",
                ["b站"],
                supplement="视频使用前后对比图，未提供同一被试者、拍摄条件、使用周期或人体功效评价材料。",
                material_type="短视频",
                scene="B站花火商单视频",
                claims=["祛痘", "使用前后对比", "完美无瑕"],
                filing_name="清颜舒缓精华",
            ),
            "expected": expected(
                "违规修改",
                ["ADLAW-028", "BILI-HUOHUA-COMPARE-VIII"],
                [
                    "【法律】《中华人民共和国广告法》第二十八条",
                    "【行政法规】《化妆品监督管理条例》第四十三条",
                    "【平台规则】哔哩哔哩《花火稿件前置审核规范总则》八、诱导类",
                ],
                [
                    legal("ADLAW-028", "无法证明同等条件的前后对比容易虚构使用效果或引人误解。"),
                    legal("COSM-REG-043", "化妆品效果展示不得含有虚假或引人误解的内容。"),
                ],
                [platform("BILI-HUOHUA-COMPARE-VIII", "视频直接使用化妆品使用前后对比图，易形成误导。")],
                ["原始图片及EXIF信息", "被试者同一性证明", "同等拍摄条件证明", "人体功效评价报告"],
                "删除前后对比及病理化画面，改为与备案功效一致的非对比性展示。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-008",
            "name": "B站专利宣称缺失专利号",
            "label": "疑似违规/需补资料",
            "test_focus": ["专利宣称", "专利号", "专利种类"],
            "input_payload": fields(
                8,
                "独家国家专利抗皱配方，专利科技让细纹消失。",
                ["b站"],
                supplement="素材未标明专利号和专利种类，也未提供有效专利证书。",
                material_type="短视频",
                scene="B站花火商单视频",
                claims=["国家专利", "专利科技抗皱"],
                filing_name="紧致抗皱精华露",
            ),
            "expected": expected(
                "需补资料",
                ["BILI-HUOHUA-PATENT-III"],
                [
                    "【法律】《中华人民共和国广告法》第十二条第一款",
                    "【平台规则】哔哩哔哩《花火稿件前置审核规范总则》三、专利数据类",
                ],
                [legal("ADLAW-012-01", "文案涉及专利产品或方法，但未标明专利号和专利种类。")],
                [platform("BILI-HUOHUA-PATENT-III", "专利和具体功效均需提供与宣称匹配的证明。")],
                ["有效专利证书", "专利权属及授权链", "专利号和专利种类", "专利技术与“细纹消失”之间的功效证据"],
                "补齐并核验专利材料，在素材中标明专利号和种类；无法证明效果时删除“让细纹消失”。",
            ),
        },
        {
            "case_id": "BEAUTY-AD-009",
            "name": "正常样例：与备案一致的清洁保湿介绍",
            "label": "正常",
            "test_focus": ["正常对照", "备案一致", "无医疗功效"],
            "input_payload": fields(
                9,
                "温和清洁肌肤，帮助保持肌肤水润。具体成分和使用方法请见产品标签。",
                ["抖音"],
                supplement="已提供普通化妆品备案信息、完整标签和功效宣称依据摘要；文案与备案一致。",
                material_type="详情页",
                scene="抖音电商商品详情页",
                claims=["清洁", "保湿"],
                filing_name="日常清洁保湿乳",
            ),
            "expected": expected(
                "无明显风险",
                [],
                ["无明确疑似违规法条；仅在已提供材料真实、有效且与实际商品一致的前提下作为正常对照样例。"],
                [
                    legal("ADLAW-008", "商品功能和成分描述应准确、清楚、明白；本样例假定已满足。", expected_hit=False),
                    legal("COSM-REG-022", "功效宣称应有科学依据；本样例假定已提供并公布摘要。", expected_hit=False),
                ],
                [platform("DOUYIN-COSM-ATTRIBUTE-2.4", "成分、含量、产地、规格等应与商品一致；本样例假定已满足。", expected_hit=False)],
                ["备案信息有效性", "产品标签与实物一致性", "功效宣称依据摘要"],
                "可作正常对照样例；上线前仍须完成商品、标签与备案一致性核验。",
                must_not_recall=["ADLAW-017", "ADLAW-028", "DOUYIN-COSM-EFFICACY-2.1.1", "DOUYIN-COSM-GUARANTEE-2.1.2"],
            ),
        },
        {
            "case_id": "BEAUTY-AD-010",
            "name": "正常样例：已显著标注广告的体验分享",
            "label": "正常",
            "test_focus": ["正常对照", "广告可识别性", "购物链接"],
            "input_payload": fields(
                10,
                "【广告】今天试用的唇釉呈现玫瑰色和光泽感，质地与上唇效果如图，详细成分请见商品页。",
                ["小红书"],
                supplement="品牌付费合作笔记，首行显著标明“广告”并附购物链接；已提供完整备案、标签和实拍原图。",
                product_category="彩妆",
                scene="小红书聚光图文笔记",
                claims=["玫瑰色", "光泽感", "上唇效果展示"],
                filing_name="玫瑰水光唇釉",
            ),
            "expected": expected(
                "无明显风险",
                [],
                ["无明确疑似违规法条；本样例仅检验已满足广告可识别性且内容与材料一致时的正常输出。"],
                [legal("INET-AD-009-03", "体验分享附购物链接时应显著标明“广告”；本样例假定首行标注清晰显著。", expected_hit=False)],
                [platform("XHS-JG-AD-ID-1.11", "聚光笔记应让消费者能够辨明其为广告；本样例假定已显著标明。", expected_hit=False)],
                ["付费合作关系", "“广告”标识在实际端的显著性截图", "商品页与实物一致性", "未经修图的原始实拍图"],
                "可作正常对照样例；投放前实机确认“广告”标识显著且不被折叠。",
                must_not_recall=["ADLAW-017", "ADLAW-009-03", "XHS-JG-COSM-EFFECT-2.1.3", "XHS-JG-COMPARE-2.15"],
            ),
        },
    ]


def main() -> None:
    payload = {
        "test_set_id": "BEAUTY-AD-COPY-20260908",
        "name": "美妆领域广告文案真实链路测试集",
        "version": "1.0",
        "purpose": "用于本地规则引擎、云端 /audit 和飞书状态机端到端测试。8条疑似违规/需补资料样例覆盖广告法、化妆品监管规则和小红书、抖音、腾讯广告、B站平台规则，2条正常样例作为对照。expected 仅表示测试期望，最终以有效规则库和人工审核为准。",
        "input_contract": "每个 case 的 input_payload 均可直接作为 /audit 请求；字段结构参照队友 health_food_ad_copy_test_set_20260906.json，并与当前 Base v4 字段命名保持一致。",
        "reference_answer_contract": {
            "compatibility": "保留队友模板的 expected_judgment、expected_routing、must_recall_rule_ids、must_not_recall_rule_ids 和 suspected_legal_basis。",
            "extensions": ["legal_provisions", "platform_provisions", "evidence_requirements", "recommended_action", "human_review_required", "reference_answer_status"],
            "platform_rule_boundary": "平台规则来自2026-09-04候选快照，动态页面须在实际投放日再核验；不得将候选条文当作生产库已生效规则。",
        },
        "cases": build_cases(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "cases": len(payload["cases"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
