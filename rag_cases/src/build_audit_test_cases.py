#!/usr/bin/env python3
"""Build a reviewed selection of candidate ad materials for /audit testing."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CANDIDATES_DIR = Path("data/structured_candidates")
DEFAULT_OUTPUT_PATH = Path("data/audit_test_cases/real_mvp_cases_v0.1.json")
DEFAULT_REPORT_PATH = Path("data/reports/audit_test_case_selection_report.md")


@dataclass(frozen=True)
class Selection:
    source_case_id: str
    case_id: str
    case_name: str
    industry: str
    content: str
    platform: tuple[str, ...]
    material_type: str
    product_category: str
    extras: dict[str, Any]
    expected_risk_level: str
    expected_routing: str
    expected_violation_types: tuple[str, ...]
    human_reason: str
    notes: str = ""
    supplement: str = ""
    urgency: str = "普通"


SELECTIONS = (
    # 游戏 5 条
    Selection(
        "sector_docx__game__19894e09",
        "REAL-GAME-001",
        "游戏充值奖励允诺不清",
        "游戏",
        "充三元送一只狗，充六元送神兽白虎，充十元就送召唤月灵",
        ("抖音",),
        "短视频",
        "网络游戏",
        {"游戏名称": "赤沙龙城", "核心宣传点": ["充值奖励"], "物料涉及场景": "买量短视频"},
        "高",
        "法务",
        ("虚假宣传",),
        "文案将充值金额与特定奖励直接对应，未说明随机抽取或其他限制条件，可能使用户误解奖励获取方式。",
    ),
    Selection(
        "sector_docx__game__d9a46e29",
        "REAL-GAME-002",
        "盲盒概率鉴定背书宣称",
        "游戏",
        "商品概率经司法鉴定真实有效，请放心购买",
        ("APP", "小程序"),
        "图文",
        "盲盒",
        {"核心宣传点": ["抽取概率", "司法鉴定背书"], "物料涉及场景": "APP和小程序主页面"},
        "高",
        "法务",
        ("虚假宣传", "引证内容不规范"),
        "文案以司法鉴定为概率真实性背书；鉴定范围和实时运行概率是否一致属于关键事实，需法务核验。",
    ),
    Selection(
        "sector_docx__game__4cff4dd4",
        "REAL-GAME-003",
        "游戏福利码奖励条件不清",
        "游戏",
        "888888仙玉+经验丹+六阶仙器8",
        ("其他",),
        "其他",
        "网络游戏",
        {"游戏名称": "大话西游归来", "核心宣传点": ["福利码", "游戏道具"], "物料涉及场景": "福利码推广"},
        "中",
        "运营补资料",
        ("虚假宣传",),
        "文案列出可领取道具但未说明兑换、账号、时间或概率条件，需要补充完整活动规则后判断。",
        "边界模糊案例；原候选材料记载法院认为表达不够清楚准确，但未认定达到欺诈程度。",
    ),
    Selection(
        "sector_docx__game__b5daf3c4",
        "REAL-GAME-004",
        "游戏超高爆率宣传",
        "游戏",
        "超高爆率乐翻天",
        ("其他",),
        "其他",
        "捕鱼游戏",
        {"核心宣传点": ["高爆率"], "物料涉及场景": "游戏推广", "证明材料情况": "暂无"},
        "中",
        "运营补资料",
        ("虚假宣传",),
        "“超高爆率”涉及可验证的游戏概率或效果，需补充概率公示、运行规则和证明材料。",
        "边界模糊案例；原候选材料记载法院将其理解为可能达到的效果。",
    ),
    Selection(
        "sector_docx__game__cc400e61",
        "REAL-GAME-005",
        "游戏专属客服单独宣称",
        "游戏",
        "专属客服",
        ("其他",),
        "其他",
        "网络游戏",
        {"核心宣传点": ["VIP权益"], "物料涉及场景": "VIP特权专区"},
        "低",
        "运营",
        ("其他",),
        "仅看“专属客服”这一条物料，未出现明显违法用语；仍应保证服务对象、条件和实际履行与宣传一致。",
        "低风险边界样本；不能据此替代对完整VIP权益页面和实际履约情况的核验。",
    ),
    # 美妆 5 条
    Selection(
        "sector_docx__beauty__5560f828",
        "REAL-COSM-001",
        "美妆产品杀菌消炎医疗用语",
        "美妆",
        "杀菌、消炎、镇痛",
        ("微信公众号", "线下"),
        "图文",
        "美容产品",
        {"核心宣称功效": ["杀菌", "消炎", "镇痛"], "物料涉及场景": "公众号、手册和挂纸宣传"},
        "高",
        "法务",
        ("涉医疗宣传", "虚假宣传"),
        "化妆品或美容产品使用杀菌、消炎、镇痛等疾病治疗或医疗作用用语，存在明显医疗化宣传风险。",
    ),
    Selection(
        "sector_docx__beauty__6091c23e",
        "REAL-COSM-002",
        "美妆服务多项最高级表述",
        "美妆",
        "材料最放心、效果最完美、质量最无忧",
        ("线下",),
        "图文",
        "美容服务",
        {"核心宣称功效": ["效果最完美"], "物料涉及场景": "经营场所展板"},
        "高",
        "法务",
        ("绝对化用语",),
        "文案连续使用“最放心”“最完美”“最无忧”等最高级、保证性表达，绝对化用语风险明显。",
    ),
    Selection(
        "sector_docx__beauty__80f1858a",
        "REAL-COSM-003",
        "面膜渗透力倍数功效宣称",
        "美妆",
        "渗透力高达70倍",
        ("天猫",),
        "详情页",
        "面膜",
        {"产品备案名称": "舒盈补水保湿蚕丝玻尿酸面膜", "核心宣称功效": ["渗透力高达70倍"], "证明材料情况": "暂无"},
        "中",
        "运营补资料",
        ("虚假宣传", "引证内容不规范"),
        "量化倍数功效需要明确比较基准、测试方法和证明材料，现有信息不足以验证“70倍”。",
    ),
    Selection(
        "sector_docx__beauty__ad8eba05",
        "REAL-COSM-004",
        "普通化妆品美白祛斑宣称",
        "美妆",
        "美白、祛斑、提亮肤色",
        ("拼多多",),
        "详情页",
        "精华液",
        {"产品备案名称": "377烟酰胺亮肤精华液", "核心宣称功效": ["美白", "祛斑", "提亮肤色"], "是否特殊化妆品": "否"},
        "高",
        "法务",
        ("虚假宣传",),
        "现有候选材料记载产品为普通化妆品，网页却宣传美白、祛斑等特殊功效，需核验备案和功效依据。",
    ),
    Selection(
        "sector_docx__beauty__b7712cbc",
        "REAL-COSM-005",
        "普通化妆品防晒功效宣称",
        "美妆",
        "防晒",
        ("天猫",),
        "详情页",
        "化妆品",
        {"核心宣称功效": ["防晒"], "是否特殊化妆品": "否", "证明材料情况": "暂无"},
        "中",
        "运营补资料",
        ("虚假宣传",),
        "防晒属于需要结合产品注册备案和功效评价判断的宣称，现有输入需补充产品资质及证明材料。",
        "缺少事实材料样本。",
    ),
    # 保健食品 5 条
    Selection(
        "sector_docx__health__47adc1ea",
        "REAL-HF-001",
        "普通食品包装宣称预防肿瘤",
        "保健食品",
        "具有增强免疫力，延缓衰老，预防心脑血管硬化，抑制肿瘤发生和生长等作用",
        ("线下",),
        "其他",
        "食用农产品",
        {"产品备案名称": "高垭口绿色鸡蛋", "核心宣称功效": ["增强免疫力", "预防心脑血管硬化", "抑制肿瘤"], "物料涉及场景": "包装标签"},
        "高",
        "法务",
        ("涉医疗宣传", "虚假宣传"),
        "食用农产品包装宣称预防心脑血管疾病、抑制肿瘤等疾病预防治疗功能，风险明显。",
    ),
    Selection(
        "sector_docx__health__d8460228",
        "REAL-HF-002",
        "普通食品朋友圈宣称治疗癌症",
        "保健食品",
        "治疗肝癌、肺癌、结肠癌等80%-90%癌症病类",
        ("微信朋友圈",),
        "图文",
        "果汁饮品",
        {"核心宣称功效": ["治疗癌症"], "物料涉及场景": "朋友圈推广", "产品属性": "普通食品"},
        "高",
        "法务",
        ("涉医疗宣传", "虚假宣传"),
        "普通食品直接宣称可治疗多种癌症，属于明显的疾病治疗功效宣传。",
    ),
    Selection(
        "sector_docx__health__70bd40e0",
        "REAL-HF-003",
        "会销普通食品逆转慢性病宣称",
        "保健食品",
        "逆转衰老，消除多种老年慢性病",
        ("线下会销",),
        "图文",
        "普通食品",
        {"产品备案名称": "昆虫蛋白", "核心宣称功效": ["逆转衰老", "消除慢性病"], "物料涉及场景": "PPT会销"},
        "高",
        "法务",
        ("涉医疗宣传", "虚假宣传"),
        "普通食品通过会销宣称能够逆转衰老、消除慢性病，涉及疾病治疗和无法证实的功效承诺。",
    ),
    Selection(
        "sector_docx__health__df7e40d5",
        "REAL-HF-004",
        "保健食品清除血管斑块宣称",
        "保健食品",
        "清除血液垃圾斑块，针对心脑血管疾病及症状作用明显",
        ("线下",),
        "图文",
        "保健食品",
        {"产品备案名称": "欣方牌瑞雪胶囊", "核心宣称功效": ["清除血液斑块", "改善心脑血管疾病"], "物料涉及场景": "横幅和海报"},
        "高",
        "法务",
        ("涉医疗宣传", "虚假宣传"),
        "保健食品宣称清除斑块并对心脑血管疾病作用明显，超出一般保健功能并涉及疾病治疗暗示。",
    ),
    Selection(
        "sector_docx__health__f92a771c",
        "REAL-HF-005",
        "保健食品批准功能对照样本",
        "保健食品",
        "补充钙",
        ("线下",),
        "其他",
        "保健食品",
        {"产品备案名称": "奇宇牌钙咀嚼片", "核心宣称功效": ["补充钙"], "批准功能": "补充钙"},
        "无明显风险",
        "运营",
        (),
        "现有候选材料明确记载该产品批准功能为“补充钙”，单独使用该表述未见明显疾病治疗或夸大功效内容。",
        "无明显风险对照样本；仅评价当前单条物料，不覆盖原案例中的其他标签表述。",
    ),
    # 通用广告 5 条
    Selection(
        "excel_candidate__absolute_terms__1c28d555",
        "REAL-GEN-001",
        "服务品牌第一宣称",
        "通用",
        "阳光车导专车私导第一品牌",
        ("官网",),
        "详情页",
        "旅游服务",
        {"物料涉及场景": "官网品牌宣传"},
        "高",
        "法务",
        ("绝对化用语",),
        "“第一品牌”属于排名和最高级表达，需要审查绝对化用语风险及客观依据。",
    ),
    Selection(
        "excel_candidate__real_estate_misleading__c7de0984",
        "REAL-GEN-002",
        "房地产固定回报承诺",
        "通用",
        "在微信公众号发布广告，含有前五年固定回报（分别为6%、6%、7%、8%、9%）等升值承诺内容",
        ("微信公众号",),
        "图文",
        "房地产",
        {"核心宣传点": ["固定回报", "升值承诺"], "物料涉及场景": "公众号推广"},
        "高",
        "法务",
        ("虚假宣传",),
        "房地产广告明确承诺固定比例回报和升值收益，存在投资回报承诺及误导风险。",
    ),
    Selection(
        "excel_candidate__improper_citation__f79ab438",
        "REAL-GEN-003",
        "医疗统计数据未标出处",
        "通用",
        "我国每年肝癌发生病例占全球肝癌发生病例的55%",
        ("微信公众号",),
        "图文",
        "医疗科技服务",
        {"核心宣传点": ["肝癌发生率统计"], "证明材料情况": "暂无", "物料涉及场景": "公众号广告"},
        "中",
        "运营补资料",
        ("引证内容不规范",),
        "文案使用精确统计数据但现有物料未提供出处、适用年份和统计口径，需要补充可核验来源。",
        "缺少事实材料样本。",
    ),
    Selection(
        "excel_candidate__false_misleading_claim__a55ab6a8",
        "REAL-GEN-004",
        "理疗产品抑制癌细胞宣称",
        "通用",
        "抑制癌细胞",
        ("线下会销",),
        "图文",
        "电热褥垫",
        {"核心宣称功效": ["抑制癌细胞"], "物料涉及场景": "经营场所PPT"},
        "高",
        "法务",
        ("涉医疗宣传", "虚假宣传"),
        "普通理疗产品直接使用抑制癌细胞的疾病治疗功效表述，存在明显医疗宣传和虚假功效风险。",
    ),
    Selection(
        "excel_candidate__live_commerce_ad__a298aa7b",
        "REAL-GEN-005",
        "食品治疗白血病宣称",
        "通用",
        "对治疗白血病有很好疗效",
        ("航空期刊",),
        "图文",
        "蛹虫草产品",
        {"核心宣称功效": ["治疗白血病"], "物料涉及场景": "期刊广告"},
        "高",
        "法务",
        ("涉医疗宣传", "虚假宣传"),
        "食品或普通商品宣称对白血病具有治疗效果，容易与药品相混淆并涉及疾病治疗功效。",
    ),
)


def load_candidate(candidates_dir: Path, case_id: str) -> dict[str, Any]:
    path = candidates_dir / f"{case_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Candidate not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_case(selection: Selection, source: dict[str, Any]) -> dict[str, Any]:
    claims = source.get("illegal_claims") or []
    if selection.content not in claims:
        raise ValueError(
            f"{selection.case_id}: selected content is not an exact illegal_claims value "
            f"from {selection.source_case_id}"
        )

    record_id = selection.case_id.lower().replace("-", "_")
    return {
        "case_id": selection.case_id,
        "case_name": selection.case_name,
        "input_payload": {
            "record_id": record_id,
            "mode": "标准",
            "industry": selection.industry,
            "content": selection.content,
            "urgency": selection.urgency,
            "supplement": selection.supplement,
            "platform": list(selection.platform),
            "material_type": selection.material_type,
            "product_category": selection.product_category,
            "extras": selection.extras,
        },
        "human_reference": {
            "expected_risk_level": selection.expected_risk_level,
            "expected_routing": selection.expected_routing,
            "expected_violation_types": list(selection.expected_violation_types),
            "human_reason": selection.human_reason,
            "notes": selection.notes,
        },
        "provenance": {
            "derived_from_case_id": source.get("case_id"),
            "source_type": source.get("source_type"),
            "source_name": source.get("source_name"),
            "source_url": source.get("source_url"),
            "source_verification_status": source.get("source_verification_status"),
            "review_status": source.get("review_status"),
            "approved_for_rag": bool(source.get("approved_for_rag", False)),
            "use_limit": "仅用于/audit规则引擎测试；原候选案例待来源核验，不得视为已确认处罚事实。",
        },
    }


def build_dataset(candidates_dir: Path) -> list[dict[str, Any]]:
    return [build_case(item, load_candidate(candidates_dir, item.source_case_id)) for item in SELECTIONS]


def write_report(cases: list[dict[str, Any]], report_path: Path) -> None:
    industries = Counter(case["input_payload"]["industry"] for case in cases)
    risks = Counter(case["human_reference"]["expected_risk_level"] for case in cases)
    routes = Counter(case["human_reference"]["expected_routing"] for case in cases)
    lines = [
        "# /audit 真实物料测试案例选择报告",
        "",
        "> 本批数据由现有待核验候选案例中的 `illegal_claims` 逐字抽取。原候选案例均未完成 source_url 核验，本文件只用于规则引擎测试，不属于 production RAG。",
        "",
        "## 汇总",
        "",
        f"- 总数：{len(cases)}",
        "- 行业分布：" + "；".join(f"{key} {industries[key]} 条" for key in ("美妆", "保健食品", "游戏", "通用")),
        "- 风险分布：" + "；".join(f"{key} {risks[key]} 条" for key in ("高", "中", "低", "无明显风险")),
        "- 路由分布：" + "；".join(f"{key} {routes[key]} 条" for key in ("运营", "运营补资料", "法务")),
        "",
        "## 已选案例",
        "",
        "| 测试案例 | 行业 | 风险 | 路由 | 原候选案例 | 广告文案 |",
        "|---|---|---|---|---|---|",
    ]
    for case in cases:
        payload = case["input_payload"]
        human = case["human_reference"]
        source = case["provenance"]
        content = payload["content"].replace("|", "\\|")
        lines.append(
            f"| {case['case_id']} {case['case_name']} | {payload['industry']} | "
            f"{human['expected_risk_level']} | {human['expected_routing']} | "
            f"{source['derived_from_case_id']} | {content} |"
        )
    lines.extend(
        [
            "",
            "## 使用限制",
            "",
            "- `/audit` 请求时只发送 `input_payload`；`human_reference` 仅用于评估，`provenance` 仅用于回溯。",
            "- 不得把本测试集作为已核验行政处罚事实或 production RAG 数据使用。",
            "- “低”和“无明显风险”只表示对当前单条广告物料的预期，不代表对原案例全部行为的判断。",
            "- 完成 source_url 核验前，不应对外引用原处罚机关、金额或裁判结论。",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates-dir", type=Path, default=DEFAULT_CANDIDATES_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = build_dataset(args.candidates_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(cases, args.report)
    print(f"Built {len(cases)} /audit test cases: {args.output}")
    print(f"Selection report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
