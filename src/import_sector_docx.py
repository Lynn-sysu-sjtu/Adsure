import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


DEFAULT_INPUT_PATH = Path("data/imports/违法广告行政处罚案例汇总_近三年_游戏美妆保健品 (1).docx")
DEFAULT_CANDIDATES_DIR = Path("data/structured_candidates")
DEFAULT_REPORTS_DIR = Path("data/reports")
DEFAULT_ANALYSIS_DIR = Path("data/analysis")
DEFAULT_MAPPINGS_DIR = Path("data/mappings")

SOURCE_TYPE = "manual_docx_sector_report_pending_source_verification"
SOURCE_NAME = "违法广告行政处罚案例汇总_近三年_游戏美妆保健品.docx"
NOTES = "DOCX三赛道人工检索候选案例，缺少source_url，需来源核验和法务复核后方可进入production RAG。"

HEADERS = [
    "序号",
    "违法类型",
    "案例名称",
    "案号",
    "审理法院",
    "审理日期",
    "关键违法事实",
    "处罚依据",
    "处罚结果",
]

SECTOR_HEADINGS = {
    "游戏领域违法广告案例": ("game", "游戏"),
    "美妆领域违法广告案例": ("beauty", "美妆"),
    "保健品领域违法广告案例": ("health", "保健品"),
}

SECTOR_CN = {"game": "游戏", "beauty": "美妆", "health": "保健品"}
INDUSTRY = {
    "game": "游戏",
    "beauty": "化妆品 / 医疗美容 / 美妆",
    "health": "保健食品 / 保健品 / 普通食品",
}

RISK_MAPPING = {
    ("game", "游戏广告允诺不准确"): ["游戏广告允诺不清楚", "奖励承诺不准确", "广告内容真实性", "虚假宣传"],
    ("game", "盲盒概率虚假宣传"): ["游戏抽奖概率公示", "盲盒概率虚假宣传", "广告内容真实性", "虚假宣传"],
    ("game", "游戏抽奖概率争议"): ["游戏抽奖概率公示", "概率规则透明度", "消费者权益争议"],
    ("game", "捕鱼游戏爆率宣传争议"): ["游戏爆率宣传", "广告夸张表达", "消费者权益争议"],
    ("game", "游戏福利码宣传争议"): ["游戏福利承诺", "奖励获取条件不清楚", "广告内容真实性"],
    ("game", "盲盒抽奖概率真实性验证"): ["游戏抽奖概率公示", "概率规则透明度", "消费者权益争议"],
    ("game", "游戏广告虚假宣传"): ["广告内容真实性", "虚假宣传", "奖励承诺不准确"],
    ("beauty", "化妆品广告使用医疗用语"): ["化妆品医疗化宣传", "涉医疗宣传", "医疗用语"],
    ("beauty", "医美机构多项广告违法"): ["医疗广告未经审查", "医美广告违规", "虚假宣传", "医疗器械合规"],
    ("beauty", "化妆品保健品虚假宣传"): ["化妆品虚假宣传", "保健品虚假宣传", "功效无依据", "涉医疗宣传"],
    ("beauty", "化妆品虚假广告及医疗用语"): ["化妆品医疗化宣传", "虚假宣传", "医疗用语", "功效夸大"],
    ("health", "会销保健品虚假宣传"): ["保健品违规宣传", "会销虚假宣传", "疾病治疗功效宣传", "老年人营销风险"],
    ("health", "食用农产品标签涉及疾病治疗功能"): ["普通食品疾病治疗功效宣传", "食品标签违法", "涉医疗宣传"],
    ("health", "保健品虚假宣传"): ["保健品虚假宣传", "功效无依据", "涉医疗宣传", "网络营销风险"],
    ("health", "保健品功能虚假宣传"): ["保健品功能虚假宣传", "功效夸大", "医疗用语", "虚假宣传"],
}

RULE_MAPPING = {
    ("game", "游戏广告允诺不准确"): "GAME_AD_REWARD_PROMISE_ACCURACY",
    ("game", "盲盒概率虚假宣传"): "GAME_LOOT_BOX_PROBABILITY_DISCLOSURE",
    ("game", "游戏抽奖概率争议"): "GAME_DRAW_PROBABILITY_TRANSPARENCY",
    ("game", "盲盒抽奖概率真实性验证"): "GAME_DRAW_PROBABILITY_TRANSPARENCY",
    ("game", "捕鱼游戏爆率宣传争议"): "GAME_HIGH_DROP_RATE_CLAIM",
    ("game", "游戏福利码宣传争议"): "GAME_BENEFIT_CODE_REWARD_CONDITION",
    ("game", "游戏广告虚假宣传"): "GAME_AD_REWARD_PROMISE_ACCURACY",
    ("beauty", "化妆品广告使用医疗用语"): "COSMETIC_MEDICAL_TERMS_PROHIBITED",
    ("beauty", "医美机构多项广告违法"): "MEDICAL_BEAUTY_AD_APPROVAL_REQUIRED",
    ("beauty", "化妆品保健品虚假宣传"): "COSMETIC_FALSE_EFFICACY_CLAIM",
    ("beauty", "化妆品虚假广告及医疗用语"): "COSMETIC_MEDICAL_EFFECT_IMPLICATION",
    ("health", "会销保健品虚假宣传"): "HEALTH_PRODUCT_MEETING_SALES_FALSE_CLAIM",
    ("health", "食用农产品标签涉及疾病治疗功能"): "ORDINARY_FOOD_DISEASE_PREVENTION_CLAIM",
    ("health", "保健品虚假宣传"): "HEALTH_PRODUCT_NETWORK_FALSE_CLAIM",
    ("health", "保健品功能虚假宣传"): "HEALTH_FOOD_FUNCTION_GUARANTEE",
}

CHANNEL_TERMS = [
    "抖音短视频广告",
    "微信小程序",
    "微信公众号",
    "小程序",
    "APP",
    "官网",
    "手册",
    "挂纸",
    "易拉宝",
    "广告立牌",
    "会销",
    "视频宣传",
    "办公区板展",
    "包装标签",
    "微信朋友圈",
    "抖音",
    "视频",
]


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def canonical_violation_type(text: str) -> str:
    clean = re.sub(r"（[^）]*同一案件[^）]*）", "", normalize_text(text)).strip()
    return clean or normalize_text(text)


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def iter_blocks(doc: DocumentType):
    body = doc.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, doc)
        elif isinstance(child, CT_Tbl):
            yield Table(child, doc)


def table_rows(table: Table) -> list[dict[str, str]]:
    if not table.rows:
        return []
    headers = [normalize_text(cell.text) for cell in table.rows[0].cells]
    if len(set(HEADERS).intersection(headers)) < 6:
        return []
    rows = []
    for row in table.rows[1:]:
        values = [normalize_text(cell.text) for cell in row.cells]
        record = {header: values[idx] if idx < len(values) else "" for idx, header in enumerate(headers)}
        if record.get("案例名称") and record.get("关键违法事实"):
            rows.append(record)
    return rows


def split_docx(doc: DocumentType) -> tuple[list[tuple[str, dict[str, str]]], list[str], list[str]]:
    current_sector: str | None = None
    in_trends = False
    in_suggestions = False
    trend_lines: list[str] = []
    suggestion_lines: list[str] = []
    records: list[tuple[str, dict[str, str]]] = []

    for block in iter_blocks(doc):
        if isinstance(block, Paragraph):
            text = normalize_text(block.text)
            if not text:
                continue
            for marker, (sector, _sector_cn) in SECTOR_HEADINGS.items():
                if marker in text:
                    current_sector = sector
                    in_trends = False
                    in_suggestions = False
                    break
            if "三大领域执法趋势分析" in text:
                current_sector = None
                in_trends = True
                in_suggestions = False
                continue
            if "合规建议" in text and in_trends:
                in_suggestions = True
                in_trends = False
                continue
            if in_suggestions:
                suggestion_lines.append(text)
            elif in_trends:
                trend_lines.append(text)
            continue
        if isinstance(block, Table) and current_sector:
            for row in table_rows(block):
                records.append((current_sector, row))
    return records, trend_lines, suggestion_lines


def make_case_id(sector: str, case_number: str, title: str, court: str, decision_date: str) -> str:
    basis = case_number or f"{title}{court}{decision_date}"
    return f"sector_docx__{sector}__{stable_hash(basis)}"


def duplicate_basis(case: dict) -> str:
    return case.get("case_number") or f"{case.get('title', '')}{case.get('court', '')}{case.get('decision_date', '')}"


def extract_claims(facts: str) -> list[str]:
    claims = [claim.strip() for claim in re.findall(r"[“\"]([^”\"]{2,100})[”\"]", facts) if claim.strip()]
    if claims:
        return list(dict.fromkeys(claims))
    terms = [
        "降血压",
        "心脑血管",
        "抑制肿瘤",
        "消炎",
        "杀菌",
        "概率",
        "高爆率",
        "福利码",
        "治疗",
        "医疗",
    ]
    sentences = [part.strip() for part in re.split(r"[。；;]", facts) if part.strip()]
    return [sentence for sentence in sentences if any(term in sentence for term in terms)][:3]


def extract_ad_channel(facts: str) -> str:
    found = [term for term in CHANNEL_TERMS if term in facts]
    return "、".join(dict.fromkeys(found)) if found else "其他"


def extract_product_or_service(sector: str, facts: str) -> str | None:
    game = re.search(r"游戏《([^》]+)》", facts)
    if game:
        return f"游戏《{game.group(1)}》"
    quoted = re.findall(r"[“\"]([^”\"]{2,40})[”\"]", facts)
    if quoted:
        return quoted[0]
    if sector == "beauty" and "医美" in facts:
        return "医美服务"
    if sector == "health" and "会销" in facts:
        return "保健品会销服务"
    return None


def extract_penalty_authority(title: str, facts: str, penalty_result: str) -> str | None:
    text = f"{title} {facts} {penalty_result}"
    match = re.search(r"([\u4e00-\u9fa5]{2,}(?:市场监督管理局|市监局|工商行政管理局))", text)
    return match.group(1) if match else None


def extract_party_name(title: str, authority: str | None) -> str | None:
    text = title
    if authority:
        text = text.replace(authority, "")
    text = re.sub(r"(?:申请执行|诉|与|、)", " ", text)
    text = re.sub(r"(?:行政处罚案|行政案|网络服务合同纠纷案|服务合同纠纷案|合同纠纷案|买卖合同纠纷案)$", "", text)
    parts = [part.strip(" ，、") for part in text.split() if part.strip(" ，、")]
    return max(parts, key=len)[:80] if parts else None


def infer_case_nature(title: str, case_number: str, facts: str, penalty_result: str) -> str:
    text = f"{title} {case_number} {facts} {penalty_result}"
    civil_markers = ["合同纠纷", "网络服务合同", "网络购物", "买卖合同", "产品责任纠纷", "消费者"]
    if any(marker in text for marker in civil_markers):
        if any(marker in text for marker in ["市监局", "市场监督管理局", "行政处罚", "罚款"]):
            return "civil_dispute_with_regulatory_signal"
        return "judicial_reference_not_admin_penalty"
    if any(marker in text for marker in ["申请执行", "行审", "非诉"]):
        return "administrative_nonlitigation_enforcement"
    if any(marker in text for marker in ["行政处罚案", "行政案", "行终", "行初"]):
        return "administrative_litigation_review"
    if any(marker in text for marker in ["市监局罚款", "市场监督管理局罚款", "行政处罚决定", "罚款"]):
        return "administrative_penalty"
    return "judicial_reference_not_admin_penalty"


def source_lookup_priority(case_nature: str) -> str:
    if case_nature in {
        "administrative_penalty",
        "administrative_nonlitigation_enforcement",
        "administrative_litigation_review",
    }:
        return "P0"
    if case_nature == "civil_dispute_with_regulatory_signal":
        return "P1"
    return "P2"


def source_lookup_query(case: dict) -> str:
    if case.get("case_number"):
        return f"{case['case_number']} {case['title']}".strip()
    return f"{case.get('title', '')} {case.get('court', '')} {case.get('violation_type', '')}".strip()


def regulatory_logic(sector: str, violation_type: str, facts: str, legal_basis: str) -> str:
    basis = f"，报告列明依据为{legal_basis}" if legal_basis else ""
    if sector == "game":
        return f"游戏广告对充值奖励、抽奖概率或福利码获取条件作出宣传时，应准确、清楚说明限制条件；本案涉及{violation_type}，相关表达可能造成消费者对奖励或概率规则的误解{basis}。"
    if sector == "beauty":
        return f"化妆品及美容服务广告不得使用疾病治疗、医疗作用、杀菌消炎等医疗用语；本案涉及{violation_type}，功效表达可能构成虚假宣传或非医疗广告使用医疗用语风险{basis}。"
    return f"保健食品、普通食品或食用农产品不得宣称疾病预防、治疗功能；本案涉及{violation_type}，相关宣传可能构成虚假宣传或食品标签违法风险{basis}。"


def vector_text(case: dict) -> str:
    claims = "；".join(case.get("illegal_claims") or []) or case.get("facts_summary", "")
    basis = "；".join(case.get("legal_basis") or []) or "待补充"
    return (
        f"【赛道】{case['sector_cn']}。"
        f"【场景】{case.get('ad_channel') or '其他'}。"
        f"【宣称】{claims}。"
        f"【风险】{case['regulatory_logic']}。"
        f"【依据】{basis}。"
        f"【结果】{case.get('penalty_result') or '待补充'}。"
    )


def build_case(sector: str, row: dict[str, str]) -> dict:
    violation_type = canonical_violation_type(row.get("违法类型", ""))
    title = normalize_text(row.get("案例名称", ""))
    case_number = normalize_text(row.get("案号", ""))
    court = normalize_text(row.get("审理法院", ""))
    decision_date = normalize_text(row.get("审理日期", ""))
    facts = normalize_text(row.get("关键违法事实", ""))
    basis = normalize_text(row.get("处罚依据", ""))
    penalty_result = normalize_text(row.get("处罚结果", ""))
    nature = infer_case_nature(title, case_number, facts, penalty_result)
    authority = extract_penalty_authority(title, facts, penalty_result)
    risks = RISK_MAPPING.get((sector, violation_type), ["虚假宣传"])
    case = {
        "case_id": make_case_id(sector, case_number, title, court, decision_date),
        "title": title,
        "case_number": case_number or None,
        "court": court or None,
        "decision_date": decision_date or None,
        "source_type": SOURCE_TYPE,
        "source_name": SOURCE_NAME,
        "source_url": None,
        "source_verification_status": "pending_source_lookup",
        "publish_date": None,
        "penalty_authority": authority,
        "party_name": extract_party_name(title, authority),
        "region": court[: min(len(court), 6)] if court else None,
        "industry": INDUSTRY[sector],
        "sector": sector,
        "sector_cn": SECTOR_CN[sector],
        "violation_type": violation_type,
        "case_nature": nature,
        "source_lookup_priority": source_lookup_priority(nature),
        "is_admin_penalty_candidate": nature
        in {
            "administrative_penalty",
            "administrative_nonlitigation_enforcement",
            "administrative_litigation_review",
        },
        "is_litigation_reference": nature != "administrative_penalty",
        "duplicate_group_id": None,
        "related_sectors": [sector],
        "product_or_service": extract_product_or_service(sector, facts),
        "ad_channel": extract_ad_channel(facts),
        "risk_dimensions": risks,
        "illegal_claims": extract_claims(facts),
        "facts_summary": facts,
        "legal_basis": [basis] if basis else [],
        "penalty_result": penalty_result,
        "penalty_amount": None,
        "regulatory_logic": regulatory_logic(sector, violation_type, facts, basis),
        "mapped_rule_ids": [],
        "keywords": list(dict.fromkeys([sector, SECTOR_CN[sector], violation_type, *risks, *extract_claims(facts)])),
        "rag_chunk_type": "case_summary",
        "review_status": "pending_review",
        "approved_for_rag": False,
        "notes": NOTES,
        "audit": {
            "review_status": "pending_review",
            "reviewer": "",
            "review_date": "",
            "review_notes": "Imported from DOCX sector report; source_url pending verification.",
            "approved_for_rag": False,
        },
    }
    case["source_lookup_query"] = source_lookup_query(case)
    case["vector_text"] = vector_text(case)
    return case


def apply_duplicate_groups(cases: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        groups[duplicate_basis(case)].append(case)
    duplicate_groups = {}
    for basis, items in groups.items():
        sectors = sorted({item["sector"] for item in items})
        if len(items) <= 1 or len(sectors) <= 1:
            continue
        group_id = f"duplicate_group__{stable_hash(basis)}"
        for item in items:
            item["duplicate_group_id"] = group_id
            item["related_sectors"] = sectors
        duplicate_groups[group_id] = items
    return duplicate_groups


def write_analysis(trend_lines: list[str], suggestion_lines: list[str], analysis_dir: Path) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    trend_content = [
        "# 三大领域执法趋势分析",
        "",
        "## 游戏领域",
        "",
        "* 概率公示合规成为核心监管要求",
        "* 广告宣传用语须准确清楚",
        "* 法院对“欺诈”认定持审慎态度",
        "",
        "## 美妆领域",
        "",
        "* 医疗用语是美妆广告红线",
        "* 虚假功效宣传处罚力度大",
        "* 医美广告须经审查",
        "",
        "## 保健品领域",
        "",
        "* 会销模式是重点监管对象",
        "* 普通食品不得宣称疾病预防治疗功能",
        "* 网络营销虚假宣传风险高",
        "",
        "## 原文摘录",
        "",
        *[f"- {line}" for line in trend_lines],
        "",
    ]
    suggestion_content = [
        "# 三大领域合规建议",
        "",
        "## 游戏企业",
        "",
        "## 美妆企业",
        "",
        "## 保健品企业",
        "",
        "## 原文摘录",
        "",
        *[f"- {line}" for line in suggestion_lines],
        "",
    ]
    (analysis_dir / "sector_enforcement_trends.md").write_text("\n".join(trend_content), encoding="utf-8")
    (analysis_dir / "sector_compliance_suggestions.md").write_text(
        "\n".join(suggestion_content),
        encoding="utf-8",
    )


def write_lookup_todo(cases: list[dict], reports_dir: Path) -> None:
    path = reports_dir / "sector_source_lookup_todo.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "sector",
                "title",
                "case_number",
                "court",
                "decision_date",
                "violation_type",
                "case_nature",
                "source_lookup_query",
                "status",
            ],
        )
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "sector": case["sector"],
                    "title": case.get("title") or "",
                    "case_number": case.get("case_number") or "",
                    "court": case.get("court") or "",
                    "decision_date": case.get("decision_date") or "",
                    "violation_type": case.get("violation_type") or "",
                    "case_nature": case.get("case_nature") or "",
                    "source_lookup_query": case.get("source_lookup_query") or "",
                    "status": "pending_source_lookup",
                }
            )


def write_rule_candidates(cases: list[dict], mappings_dir: Path) -> int:
    mappings_dir.mkdir(parents=True, exist_ok=True)
    path = mappings_dir / "sector_case_rule_candidates.jsonl"
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for case in cases:
            suggested_rule_id = RULE_MAPPING.get((case["sector"], case["violation_type"]), "SECTOR_RULE_REVIEW_REQUIRED")
            for risk in case.get("risk_dimensions") or []:
                record = {
                    "case_id": case["case_id"],
                    "sector": case["sector"],
                    "violation_type": case["violation_type"],
                    "risk_dimension": risk,
                    "suggested_rule_id": suggested_rule_id,
                    "mapping_reason": "根据三赛道DOCX报告中的sector与违法类型生成的候选规则映射，待人工审核确认。",
                    "confidence": "medium",
                    "reviewer": "",
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    return count


def write_import_report(report: dict, reports_dir: Path) -> None:
    lines = [
        "# Sector DOCX Import Report",
        "",
        f"- Rows imported: {report['imported_count']}",
        f"- New files written: {report['new_files_count']}",
        f"- Existing duplicates kept: {report['deduplicated_existing_count']}",
        f"- Duplicate groups: {report['duplicate_group_count']}",
        f"- Rule mapping candidates: {report['rule_mapping_count']}",
        "",
        "## By Sector",
        "",
    ]
    for sector, count in sorted(report["by_sector"].items()):
        lines.append(f"- {sector}: {count}")
    lines.extend(["", "## Case Nature", ""])
    for nature, count in sorted(report["by_case_nature"].items()):
        lines.append(f"- {nature}: {count}")
    lines.extend(["", "## Duplicate Cases", ""])
    if report["duplicate_groups"]:
        lines.append("| duplicate_group_id | sectors | case_numbers | titles |")
        lines.append("| --- | --- | --- | --- |")
        for item in report["duplicate_groups"]:
            lines.append(
                f"| {item['duplicate_group_id']} | {', '.join(item['sectors'])} | {', '.join(item['case_numbers'])} | {', '.join(item['titles'])} |"
            )
    else:
        lines.append("- None")
    lines.append("")
    reports_dir.joinpath("sector_docx_import_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(
    input_path: Path = DEFAULT_INPUT_PATH,
    candidates_dir: Path = DEFAULT_CANDIDATES_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    analysis_dir: Path = DEFAULT_ANALYSIS_DIR,
    mappings_dir: Path = DEFAULT_MAPPINGS_DIR,
) -> dict:
    candidates_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    doc = Document(input_path)
    records, trend_lines, suggestion_lines = split_docx(doc)
    cases = [build_case(sector, row) for sector, row in records]
    duplicate_groups = apply_duplicate_groups(cases)
    by_sector = Counter(case["sector"] for case in cases)
    by_case_nature = Counter(case["case_nature"] for case in cases)
    new_files = 0
    existing = 0
    for case in cases:
        path = candidates_dir / f"{case['case_id']}.json"
        if path.exists():
            existing += 1
            continue
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        new_files += 1
    write_analysis(trend_lines, suggestion_lines, analysis_dir)
    write_lookup_todo(cases, reports_dir)
    rule_mapping_count = write_rule_candidates(cases, mappings_dir)
    duplicate_report = [
        {
            "duplicate_group_id": group_id,
            "sectors": sorted({case["sector"] for case in items}),
            "case_numbers": sorted({case.get("case_number") or "" for case in items if case.get("case_number")}),
            "titles": sorted({case.get("title") or "" for case in items}),
        }
        for group_id, items in sorted(duplicate_groups.items())
    ]
    report = {
        "imported_count": len(cases),
        "new_files_count": new_files,
        "deduplicated_existing_count": existing,
        "by_sector": dict(by_sector),
        "by_case_nature": dict(by_case_nature),
        "duplicate_group_count": len(duplicate_groups),
        "duplicate_groups": duplicate_report,
        "rule_mapping_count": rule_mapping_count,
    }
    write_import_report(report, reports_dir)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Import sector DOCX report into candidate case JSON.")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--candidates-dir", type=Path, default=DEFAULT_CANDIDATES_DIR)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS_DIR)
    parser.add_argument("--mappings-dir", type=Path, default=DEFAULT_MAPPINGS_DIR)
    args = parser.parse_args()
    report = run(
        input_path=args.input_path,
        candidates_dir=args.candidates_dir,
        reports_dir=args.reports_dir,
        analysis_dir=args.analysis_dir,
        mappings_dir=args.mappings_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
