#!/usr/bin/env python3
"""Build the initial competition submission handbook and verified test pack."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "参赛提交材料"
AUDIT_CASES_PATH = ROOT / "data" / "audit_test_cases" / "real_mvp_cases_v0.1.json"

INDEX_VERSION = "a3163af401760571"
VALIDATION_DATE = "2026-07-19"

NAVY = "17365D"
BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
INK = "1F2937"
MUTED = "5B6573"
PALE_BLUE = "E8EEF5"
PALE_GRAY = "F2F4F7"
PALE_GOLD = "FFF6D8"
GOLD = "8A6500"
RED = "9B1C1C"
WHITE = "FFFFFF"
BORDER = "CAD5E2"
ASCII_FONT = "Calibri"
CJK_FONT = "Hiragino Sans GB"


RAG_VERIFICATION = {
    "SUBMIT-BEAUTY-001": {
        "first_hit_case_id": "sector_docx__beauty__ad8eba05",
        "first_hit_title": "陈剑力诉河南维颜化妆品有限公司网络购物合同纠纷案",
        "score": 8.723913,
        "elapsed_ms": 12.56,
        "returned_case_ids": [
            "sector_docx__beauty__ad8eba05",
            "sector_docx__beauty__1696a02c",
            "sector_docx__beauty__96b1a837",
        ],
        "recommended_query": "化妆品 美白精华 电商广告 限时降价 美白功效 宣称",
    },
    "SUBMIT-GAME-001": {
        "first_hit_case_id": "sector_docx__game__b5daf3c4",
        "first_hit_title": "孙某诉某（北京）科技有限公司网络服务合同纠纷案",
        "score": 5.672364,
        "elapsed_ms": 8.31,
        "returned_case_ids": [
            "sector_docx__game__b5daf3c4",
            "sector_docx__game__54a80f6c",
            "sector_docx__game__53e9096b",
        ],
        "recommended_query": "游戏 爆率拉满 神装随便出 抽奖概率 公示 证明材料",
    },
    "SUBMIT-HF-001": {
        "first_hit_case_id": "sector_docx__health__d8460228",
        "first_hit_title": "张某甲诉象州县某局行政处罚案",
        "score": 87.452553,
        "elapsed_ms": 15.57,
        "returned_case_ids": ["sector_docx__health__d8460228"],
        "recommended_query": "治疗肝癌、肺癌、结肠癌等80%-90%癌症病类",
    },
}


def build_submission_cases() -> list[dict]:
    """Return the three final evaluator cases in display order."""
    common_candidate_limit = (
        "仅用于 /audit 规则与 candidate_debug RAG 联调；命中的类案均待来源核验，"
        "不得视为已确认处罚事实或最终法律依据。"
    )
    return [
        {
            "case_id": "SUBMIT-BEAUTY-001",
            "case_name": "美白精华降价促销与贬损性表达",
            "input_payload": {
                "record_id": "submit_beauty_001",
                "mode": "标准",
                "industry": "美妆",
                "content": "我们的美白精华一降价，你还不是和狗一样跑过来；限时测试价（有图片）",
                "urgency": "普通",
                "supplement": "图片文字已人工抽取；需核验产品注册备案属性、功效依据和价格活动规则。",
                "platform": ["电商广告", "信息流"],
                "material_type": "图文",
                "product_category": "美白精华 / 化妆品",
                "content_nature": "ad",
                "extras": {
                    "核心宣称功效": ["美白"],
                    "图片文字": [
                        "我们的美白精华一降价",
                        "你还不是和狗一样跑过来",
                        "限时测试价",
                    ],
                    "物料涉及场景": "美白精华降价促销海报",
                    "图片标记": "有图片",
                },
            },
            "human_reference": {
                "expected_risk_level": "高",
                "expected_routing": "法务",
                "expected_violation_types": [
                    "贬损性或侮辱性表达",
                    "化妆品功效宣称",
                    "价格促销信息不完整",
                ],
                "human_reason": (
                    "文案以“和狗一样跑过来”贬损消费者，存在内容不当和品牌舆情风险；"
                    "“美白精华”涉及化妆品功效及产品属性核验，“限时测试价”还需补充"
                    "活动期限、价格依据和适用条件。"
                ),
                "notes": (
                    "候选 RAG 首条案例仅覆盖普通化妆品美白功效维度；贬损性表达和"
                    "促销价格维度仍由规则引擎与人工复核判断。"
                ),
            },
            "provenance": {
                "input_source_type": "user_provided_image_text_extraction",
                "image_filename": "codex-clipboard-e5b6c94b-bb79-41b0-be14-408719e1c7be.jpg",
                "derived_from_case_id": "sector_docx__beauty__ad8eba05",
                "source_verification_status": "pending_source_lookup",
                "review_status": "pending_review",
                "approved_for_rag": False,
                "use_limit": common_candidate_limit,
            },
        },
        {
            "case_id": "SUBMIT-GAME-001",
            "case_name": "十连抽爆率与神装奖励宣传",
            "input_payload": {
                "record_id": "submit_game_001",
                "mode": "标准",
                "industry": "游戏",
                "content": (
                    "开局十连抽；爆率拉满，神装随便出；今日开抽；"
                    "画面另有数字“50”（含义不明确）（有图片）"
                ),
                "urgency": "普通",
                "supplement": "图片文字已人工抽取；暂未提供抽取概率、奖励池、保底机制和活动规则。",
                "platform": ["信息流广告"],
                "material_type": "图文",
                "product_category": "网络游戏",
                "content_nature": "ad",
                "extras": {
                    "核心宣传点": ["十连抽", "爆率拉满", "神装随便出"],
                    "图片文字": [
                        "开局十连抽",
                        "爆率拉满，神装随便出",
                        "今日开抽",
                        "50（画面数字，含义不明确）",
                    ],
                    "物料涉及场景": "游戏抽卡信息流广告",
                    "图片标记": "有图片",
                },
            },
            "human_reference": {
                "expected_risk_level": "中",
                "expected_routing": "运营补资料",
                "expected_violation_types": [
                    "游戏爆率宣传",
                    "奖励条件不清",
                    "虚假宣传",
                ],
                "human_reason": (
                    "“爆率拉满”“神装随便出”会使玩家形成高概率或易得奖励的预期，"
                    "但当前未提供概率公示、奖励池、保底机制和限制条件；应先补齐规则"
                    "与后台数据，若宣传与实际不符再升级法务处理。"
                ),
                "notes": "图片中的数字“50”含义不明确，不把它擅自解释为确定奖励数量。",
            },
            "provenance": {
                "input_source_type": "user_provided_image_text_extraction",
                "image_filename": "codex-clipboard-742ba584-1324-4d33-be9c-ad6f13566e54.jpg",
                "derived_from_case_id": "sector_docx__game__b5daf3c4",
                "source_verification_status": "pending_source_lookup",
                "review_status": "pending_review",
                "approved_for_rag": False,
                "use_limit": common_candidate_limit,
            },
        },
        {
            "case_id": "SUBMIT-HF-001",
            "case_name": "普通食品朋友圈宣称治疗癌症",
            "input_payload": {
                "record_id": "submit_hf_001",
                "mode": "标准",
                "industry": "保健食品",
                "content": "治疗肝癌、肺癌、结肠癌等80%-90%癌症病类",
                "urgency": "普通",
                "supplement": "",
                "platform": ["微信朋友圈"],
                "material_type": "图文",
                "product_category": "果汁饮品 / 普通食品",
                "content_nature": "ad",
                "extras": {
                    "核心宣称功效": ["治疗癌症"],
                    "物料涉及场景": "朋友圈推广",
                    "产品属性": "普通食品",
                    "图片标记": "无图片",
                },
            },
            "human_reference": {
                "expected_risk_level": "高",
                "expected_routing": "法务",
                "expected_violation_types": ["涉医疗宣传", "虚假宣传"],
                "human_reason": (
                    "普通食品直接宣称可治疗肝癌、肺癌、结肠癌等多种癌症，属于明显的"
                    "疾病治疗功效宣传，应停止发布并提交法务复核。"
                ),
                "notes": "",
            },
            "provenance": {
                "input_source_type": "existing_audit_regression_case",
                "derived_from_case_id": "sector_docx__health__d8460228",
                "source_verification_status": "pending_source_lookup",
                "review_status": "pending_review",
                "approved_for_rag": False,
                "use_limit": common_candidate_limit,
            },
        },
    ]


def rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color)


def set_run_font(
    run,
    *,
    size: float = 11,
    bold: bool | None = None,
    color: str = INK,
    italic: bool = False,
    ascii_font: str = ASCII_FONT,
    cjk_font: str = CJK_FONT,
) -> None:
    run.font.name = ascii_font
    run.font.size = Pt(size)
    run.font.color.rgb = rgb(color)
    run.font.italic = italic
    if bold is not None:
        run.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), ascii_font)
    rfonts.set(qn("w:hAnsi"), ascii_font)
    rfonts.set(qn("w:eastAsia"), cjk_font)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top: int = 80, start: int = 120, bottom: int = 80, end: int = 120) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_cell_width(cell, width_dxa: int) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")
    cell.width = Inches(width_dxa / 1440)


def set_table_borders(table, color: str = BORDER, size: int = 5) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), str(size))
        tag.set(qn("w:space"), "0")
        tag.set(qn("w:color"), color)


def set_table_geometry(table, widths_dxa: list[int], *, indent_dxa: int = 120) -> None:
    if sum(widths_dxa) != 9360:
        raise ValueError(f"Table widths must total 9360 DXA: {widths_dxa}")
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr

    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), "9360")
    tbl_w.set(qn("w:type"), "dxa")

    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent_dxa))
    tbl_ind.set(qn("w:type"), "dxa")

    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)

    for row in table.rows:
        for index, cell in enumerate(row.cells):
            set_cell_width(cell, widths_dxa[index])
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_table_borders(table)


def repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_keep_together(paragraph, *, with_next: bool = False) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    keep_lines = OxmlElement("w:keepLines")
    ppr.append(keep_lines)
    if with_next:
        keep_next = OxmlElement("w:keepNext")
        ppr.append(keep_next)


def clear_cell(cell) -> None:
    paragraph = cell.paragraphs[0]
    for run in paragraph.runs:
        run._element.getparent().remove(run._element)


def write_cell(
    cell,
    text: str,
    *,
    bold: bool = False,
    color: str = INK,
    size: float = 9,
    align=WD_ALIGN_PARAGRAPH.LEFT,
) -> None:
    clear_cell(cell)
    paragraph = cell.paragraphs[0]
    paragraph.alignment = align
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.12
    run = paragraph.add_run(str(text))
    set_run_font(run, size=size, bold=bold, color=color)


def add_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
    widths_dxa: list[int],
    *,
    font_size: float = 9,
    header_fill: str = PALE_BLUE,
    first_col_bold: bool = False,
    spacer_after: bool = True,
) -> object:
    table = doc.add_table(rows=1, cols=len(headers))
    set_table_geometry(table, widths_dxa)
    for i, header in enumerate(headers):
        set_cell_shading(table.rows[0].cells[i], header_fill)
        write_cell(
            table.rows[0].cells[i],
            header,
            bold=True,
            color=NAVY,
            size=font_size,
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
    repeat_table_header(table.rows[0])
    for row_values in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row_values):
            set_cell_width(cells[i], widths_dxa[i])
            set_cell_margins(cells[i])
            cells[i].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            write_cell(
                cells[i],
                value,
                bold=first_col_bold and i == 0,
                size=font_size,
                color=NAVY if first_col_bold and i == 0 else INK,
                align=WD_ALIGN_PARAGRAPH.CENTER if i == 0 and len(value) < 12 else WD_ALIGN_PARAGRAPH.LEFT,
            )
    set_table_borders(table)
    if spacer_after:
        spacer = doc.add_paragraph()
        spacer.paragraph_format.space_before = Pt(0)
        spacer.paragraph_format.space_after = Pt(2)
    return table


def configure_document(doc: Document, running_label: str) -> None:
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(1)
    section.right_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.left_margin = Inches(1)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)

    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = ASCII_FONT
    normal.font.size = Pt(11)
    normal.font.color.rgb = rgb(INK)
    normal._element.rPr.rFonts.set(qn("w:ascii"), ASCII_FONT)
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), ASCII_FONT)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25

    heading_specs = {
        "Heading 1": (16, BLUE, 18, 10),
        "Heading 2": (13, BLUE, 14, 7),
        "Heading 3": (12, DARK_BLUE, 10, 5),
    }
    for style_name, (size, color, before, after) in heading_specs.items():
        style = styles[style_name]
        style.font.name = ASCII_FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = rgb(color)
        style._element.rPr.rFonts.set(qn("w:ascii"), ASCII_FONT)
        style._element.rPr.rFonts.set(qn("w:hAnsi"), ASCII_FONT)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), CJK_FONT)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    header = section.header
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    hp.paragraph_format.space_after = Pt(0)
    hr = hp.add_run(f"ADSURE  ·  {running_label}")
    set_run_font(hr, size=8.5, bold=True, color=MUTED)

    footer = section.footer
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    fp.paragraph_format.space_before = Pt(0)
    fr = fp.add_run("内部初版  ·  ")
    set_run_font(fr, size=8, color=MUTED)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    fp._p.append(field)


def add_title_block(doc: Document, title: str, subtitle: str, label: str) -> None:
    kicker = doc.add_paragraph()
    kicker.paragraph_format.space_before = Pt(2)
    kicker.paragraph_format.space_after = Pt(2)
    kr = kicker.add_run(label.upper())
    set_run_font(kr, size=9, bold=True, color=GOLD)

    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(5)
    tr = title_p.add_run(title)
    set_run_font(tr, size=25, bold=True, color=NAVY)
    set_keep_together(title_p, with_next=True)

    subtitle_p = doc.add_paragraph()
    subtitle_p.paragraph_format.space_before = Pt(0)
    subtitle_p.paragraph_format.space_after = Pt(12)
    sr = subtitle_p.add_run(subtitle)
    set_run_font(sr, size=11.5, color=MUTED)


def add_callout(
    doc: Document,
    label: str,
    text: str,
    *,
    fill: str = PALE_GOLD,
    color: str = GOLD,
    spacer_after: bool = True,
) -> None:
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [9360])
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    clear_cell(cell)
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.line_spacing = 1.15
    lr = p.add_run(f"{label}　")
    set_run_font(lr, size=9.2, bold=True, color=color)
    body = p.add_run(text)
    set_run_font(body, size=9.2, color=INK)
    if spacer_after:
        spacer = doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(1)


def add_body(doc: Document, text: str, *, size: float = 10.4, after: float = 5) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = 1.22
    r = p.add_run(text)
    set_run_font(r, size=size, color=INK)


def add_step(doc: Document, number: str, title: str, action: str, response: str, duration: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(5)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    badge = p.add_run(f"步骤 {number}  ")
    set_run_font(badge, size=10.5, bold=True, color=WHITE)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), BLUE)
    badge._element.get_or_add_rPr().append(shd)
    title_run = p.add_run(title)
    set_run_font(title_run, size=11, bold=True, color=NAVY)

    detail = doc.add_paragraph()
    detail.paragraph_format.left_indent = Inches(0.18)
    detail.paragraph_format.space_before = Pt(0)
    detail.paragraph_format.space_after = Pt(4)
    detail.paragraph_format.line_spacing = 1.18
    for label, value in (("用户操作", action), ("系统响应", response), ("预计耗时", duration)):
        lr = detail.add_run(f"{label}：")
        set_run_font(lr, size=9.6, bold=True, color=DARK_BLUE)
        vr = detail.add_run(value + ("　" if label != "预计耗时" else ""))
        set_run_font(vr, size=9.6, color=INK)
    set_keep_together(detail)


def add_page_break(doc: Document) -> None:
    doc.add_page_break()


def build_handbook() -> Path:
    doc = Document()
    configure_document(doc, "产品使用手册（初版）")
    add_title_block(
        doc,
        "Adsure 广告合规 AI",
        "产品使用手册（参赛提交初版）｜基于当前 Git 项目代码与本地实测",
        "Product Handbook · v0.1",
    )
    add_callout(
        doc,
        "当前版本说明",
        "本仓库交付的是广告审核案例 RAG 与接口联调能力，不含公开网页前端。候选案例仅用于 candidate_debug，必须显示“待来源核验”，不能作为已确认处罚事实。",
    )

    doc.add_heading("1. 访问方式", level=1)
    add_table(
        doc,
        ["项目", "当前初版填写", "评委使用说明"],
        [
            [
                "产品审核接口",
                "http://124.223.111.170:8504/audit",
                "来自现有联调记录；属于 API 地址，不是网页首页。赛前须再次验证可达性与版本。",
            ],
            [
                "案例 RAG",
                "http://127.0.0.1:8505/cases/retrieve",
                "本仓库默认本机/内网服务。评委样例需显式启用 candidate 模式。",
            ],
            [
                "账号 / 密码",
                "当前仓库无网页登录账号",
                "接口使用 X-API-Key；测试 Key 通过安全渠道单独交付，不写入手册、代码或 Git。",
            ],
            [
                "浏览器 / 系统",
                "Windows、macOS、Linux",
                "HTTP/JSON 接口与系统无关；可用 Postman/curl。FastAPI 本地文档可在现代 Chrome、Edge、Firefox、Safari 查看。",
            ],
        ],
        [1500, 3000, 4860],
        font_size=8.6,
        first_col_bold=True,
    )
    add_body(
        doc,
        "赛前必填项：如最终交付包含飞书或网页工作台，请将其真实链接、测试账号、密码有效期及登录步骤补入本节，并完成一次无缓存、非管理员账号验证。",
        size=9.4,
        after=3,
    )
    add_page_break(doc)
    doc.add_heading("2. 典型使用流程", level=1)
    add_table(
        doc,
        ["步骤", "用户操作", "系统响应", "预计耗时"],
        [
            [
                "1 准备物料",
                "选择行业、平台和物料类型；粘贴完整文案，按需补产品属性、备案或活动条件。",
                "校验必填字段与枚举；不合格请求返回明确错误。",
                "1–2 分钟",
            ],
            [
                "2 提交审核",
                "在工作台点击“开启 AI 审核”，或向 /audit 发送 JSON。",
                "生成请求标识，启动规则判断、风险归类和案例检索。",
                "操作 20–40 秒",
            ],
            [
                "3 查看结论",
                "核对风险等级、命中要点、修改建议、推荐违规类型和审核意见。",
                "高风险优先路由法务；依赖证明材料时提示补资料。",
                "预计 5–15 秒",
            ],
            [
                "4 核对类案",
                "查看 case_id、风险维度和监管逻辑；候选模式检查三项状态字段。",
                "同一案例去重后返回 Top 1–3；三条最终样例均首条命中。",
                "本机 6–11 ms；端到端通常 <1 秒",
            ],
            [
                "5 处理流转",
                "修改文案、补充材料，或提交法务复核；保留原物料和请求标识。",
                "上层状态机回写审核字段，并把“法务”映射为“待法务复核”。",
                "人工 1–3 分钟",
            ],
        ],
        [1350, 3100, 3480, 1430],
        font_size=8.2,
        first_col_bold=True,
    )

    doc.add_heading("3. 一次测试的通过标准", level=1)
    add_table(
        doc,
        ["检查点", "通过条件"],
        [
            ["接口", "HTTP 200，code=0；错误 Key 返回 401 且不泄露服务端凭证。"],
            ["审核", "风险、违规类型、修改建议、routing 字段结构完整；高风险样例路由法务。"],
            ["RAG", "candidate_debug 显式开启；对应 case_id 位于首条；candidate_data=true。"],
            ["边界", "页面显著提示“待来源核验，不得对外引用”，不把 BM25 score 显示为百分比相似度。"],
        ],
        [1900, 7460],
        font_size=8.5,
        first_col_bold=True,
    )
    add_callout(
        doc,
        "验收记录",
        f"2026-07-19 本地候选索引 {INDEX_VERSION}：106 个候选案例、212 个切片；三条最终样例均 HTTP 200 且预期 case_id 为第一条命中。21 项 API/测试集回归测试通过。",
        fill=PALE_BLUE,
        color=BLUE,
        spacer_after=False,
    )

    add_page_break(doc)
    doc.add_heading("4. 产品差异化", level=1)
    add_body(
        doc,
        "Adsure 解决的是“广告物料进入发布前，如何快速、可追溯地识别风险并把结果送到正确的人”的问题。它把规则结论、案例解释和流程路由拆开，避免用单一模型输出冒充法律事实。",
    )
    add_table(
        doc,
        ["对比维度", "常见方案", "Adsure 当前实现"],
        [
            ["审核效率", "人工逐条检索、复制规则", "一次请求返回风险字段、修改建议、路由及相关案例。"],
            ["可追溯性", "通用 AI 常缺少来源边界", "正式案例保留 source_url/raw_text_path；候选数据强制标记状态。"],
            ["判断稳定性", "纯关键词容易漏场景，纯模型难复核", "规则决定风险，RAG 提供类案解释；两者不互相覆盖。"],
            ["协作闭环", "结论停留在聊天或报告", "接口字段可回写飞书状态机，支持运营修改、补资料和法务复核。"],
            ["安全边界", "测试数据可能混入生产", "production 与 candidate 索引隔离；生产为空时绝不自动回退候选库。"],
        ],
        [1700, 3000, 4660],
        font_size=8.7,
        first_col_bold=True,
    )

    doc.add_heading("5. 已知问题与边界", level=1)
    add_table(
        doc,
        ["当前问题", "影响与建议"],
        [
            ["无公开网页前端/测试账号", "当前只能按 API 联调；赛前补真实入口并单独交付限时凭证。"],
            ["候选案例待核验", "106 个候选案例不得作为处罚事实；candidate_debug 仅限项目成员和评委测试。"],
            ["正式库覆盖有限", "production 为同一市场监管总局公开页的 10 起典型案例，不代表全行业覆盖。"],
            ["仅 BM25 词法检索", "尚无 Embedding/生产向量库；同义改写、极短文案可能零召回或排序波动。"],
            ["赛道枚举有限", "当前接口支持美妆、游戏、保健食品、通用；跨行业物料需人工选择最相关赛道。"],
            ["案例不是最终结论", "RAG 只用于规则解释，风险仍以规则命中、产品事实与人工复核为准。"],
            ["外部 /audit 不在本仓库", "审核引擎与 RAG 需冻结同一测试版本；IP 地址、超时和字段映射赛前复测。"],
        ],
        [2600, 6760],
        font_size=8.55,
        first_col_bold=True,
    )
    add_callout(
        doc,
        "异常应对",
        "若无案例命中：保留规则审核结果并显示“未命中可用案例”；若服务超时/503：不切换候选库，记录请求标识后重试；若行业或材料信息不足：转“运营补资料”或人工复核。",
        fill=PALE_GRAY,
        color=DARK_BLUE,
        spacer_after=False,
    )

    out = OUTPUT_DIR / "Adsure_产品使用手册_初版.docx"
    doc.save(out)
    return out


def build_machine_test_pack(selected_cases: list[dict]) -> tuple[Path, Path]:
    tests = []
    actual_records = []
    for case in selected_cases:
        verification = deepcopy(RAG_VERIFICATION[case["case_id"]])
        payload = case["input_payload"]
        retrieval_request = {
            "content": verification["recommended_query"],
            "industry": payload["industry"],
            "platform": payload["platform"],
            "top_k": 3,
        }
        test_item = {
                "test_case_id": case["case_id"],
                "test_case_name": case["case_name"],
                "track": payload["industry"],
                "background": (
                    "广告发布前审核；使用完整物料字段，不发送 human_reference 或 provenance "
                    "到线上 /audit。图片样例已人工抽取文字，并在文案末尾标注“（有图片）”。"
                ),
                "attachment_note": (
                    "（有图片）"
                    if case["provenance"].get("image_filename")
                    else "无图片"
                ),
                "image_filename": case["provenance"].get("image_filename"),
                "input_payload": payload,
                "expected_operation": [
                    "在产品中选择“标准”模式并录入 input_payload，提交 AI 审核。",
                    "确认规则结果返回风险等级、推荐违规类型、修改建议和 routing。",
                    (
                        "由审核结果生成 recommended_retrieval_text，在 candidate_debug 模式下"
                        "调用 /cases/retrieve，并核对首条 case_id。"
                    ),
                ],
                "expected_output": {
                    "expected_risk_level": case["human_reference"]["expected_risk_level"],
                    "expected_routing": case["human_reference"]["expected_routing"],
                    "expected_violation_types": case["human_reference"]["expected_violation_types"],
                    "expected_reason": case["human_reference"]["human_reason"],
                    "expected_notes": case["human_reference"].get("notes", ""),
                    "expected_first_hit_case_id": verification["first_hit_case_id"],
                    "expected_first_hit_title": verification["first_hit_title"],
                    "candidate_data": True,
                    "source_verification_status": "pending_source_lookup",
                    "review_status": "pending_review",
                    "approved_for_rag": False,
                },
                "rag_request": retrieval_request,
                "recommended_retrieval_text": verification["recommended_query"],
                "use_limit": case["provenance"]["use_limit"],
            }
        if "recommended_query_cli_score" in verification:
            test_item["recommended_retrieval_cli_expectation"] = {
                "expected_first_hit_case_id": verification["first_hit_case_id"],
                "expected_bm25_score": verification["recommended_query_cli_score"],
            }
        tests.append(test_item)
        actual_record = {
                "test_case_id": case["case_id"],
                "validation_date": VALIDATION_DATE,
                "http_status": 200,
                "index_scope": "candidate",
                "index_version": INDEX_VERSION,
                "first_hit_case_id": verification["first_hit_case_id"],
                "first_hit_title": verification["first_hit_title"],
                "bm25_score": verification["score"],
                "elapsed_ms_local_testclient": verification["elapsed_ms"],
                "rag_request_content": verification["recommended_query"],
                "returned_case_ids": verification["returned_case_ids"],
                "retrieval_method": "fielded_bm25_v2",
                "min_query_coverage": 0.25,
                "candidate_data": True,
                "source_verification_status": "pending_source_lookup",
                "review_status": "pending_review",
                "approved_for_rag": False,
            }
        if "recommended_query_cli_score" in verification:
            actual_record["recommended_query_cli_score"] = verification["recommended_query_cli_score"]
        actual_records.append(actual_record)

    package = {
        "package_name": "Adsure 评委测试样例 3 条（完整稿）",
        "version": "1.0",
        "generated_date": VALIDATION_DATE,
        "coverage": {"total": 3, "tracks": {"美妆": 1, "游戏": 1, "保健食品": 1}},
        "rag_mode": "candidate_debug",
        "index_version": INDEX_VERSION,
        "important_notice": (
            "三条样例的类案均为待来源核验候选数据，只用于规则/RAG联调，"
            "不得作为已确认处罚事实或最终法律依据。"
        ),
        "tests": tests,
    }
    record = {
        "validation_date": VALIDATION_DATE,
        "method": "FastAPI TestClient 调用当前 src.api.create_app(data_dir='data', index_scope='candidate') 的 POST /cases/retrieve；每条 top_k=3。",
        "health": {
            "status": "ok",
            "service": "adsure-rag",
            "index_scope": "candidate",
            "candidate_data": True,
            "case_count": 106,
            "chunk_count": 212,
            "index_version": INDEX_VERSION,
            "retrieval": {
                "requested_mode": "lexical",
                "effective_mode": "lexical",
                "semantic_status": "disabled",
                "retrieval_method": "fielded_bm25_v2",
                "min_query_coverage": 0.25,
            },
            "checks": {"index": "ok", "api_key": "configured"},
        },
        "regression_tests": {
            "command": "python3 -m unittest tests.test_api tests.test_audit_test_cases -v",
            "tests_run": 21,
            "result": "OK",
        },
        "records": actual_records,
    }

    package_path = OUTPUT_DIR / "Adsure_评委测试样例_3条.json"
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record_path = OUTPUT_DIR / "Adsure_评委测试样例_3条_RAG实测记录.json"
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return package_path, record_path


def add_case_detail(doc: Document, ordinal: int, case: dict) -> None:
    payload = case["input_payload"]
    expected = case["human_reference"]
    verification = RAG_VERIFICATION[case["case_id"]]
    attachment_note = "（有图片）" if case["provenance"].get("image_filename") else "无图片"
    doc.add_heading(f"{ordinal}. {case['case_name']}", level=1)
    meta = doc.add_paragraph()
    meta.paragraph_format.space_before = Pt(0)
    meta.paragraph_format.space_after = Pt(4)
    meta.paragraph_format.line_spacing = 1.05
    meta_run = meta.add_run(
        f"{payload['industry']}赛道 · {case['case_id']}　"
        f"风险={expected['expected_risk_level']}　路由={expected['expected_routing']}　"
        f"首条类案={verification['first_hit_case_id']}"
    )
    set_run_font(meta_run, size=8.2, bold=True, color=BLUE)

    doc.add_heading("输入材料", level=2)
    extras = "；".join(
        f"{key}：{('、'.join(value) if isinstance(value, list) else value)}"
        for key, value in payload["extras"].items()
    )
    add_table(
        doc,
        ["字段", "评委输入"],
        [
            ["record_id / 模式", f"{payload['record_id']} / {payload['mode']}"],
            ["行业 / 品类", f"{payload['industry']} / {payload['product_category']}"],
            ["广告文案", payload["content"]],
            ["平台 / 物料", f"{'、'.join(payload['platform'])} / {payload['material_type']}"],
            ["附件状态", attachment_note],
            ["补充信息", extras],
        ],
        [1800, 7560],
        font_size=8.15,
        first_col_bold=True,
        spacer_after=False,
    )

    doc.add_heading("预期操作与系统响应", level=2)
    add_table(
        doc,
        ["操作", "系统响应", "通过标准"],
        [
            [
                "提交 input_payload",
                "返回风险结论、推荐违规类型、修改建议和 routing。",
                f"风险={expected['expected_risk_level']}；routing={expected['expected_routing']}。",
            ],
            [
                "进入相关案例",
                "以 candidate_debug 检索并显示候选态提示。",
                f"首条 case_id={verification['first_hit_case_id']}。",
            ],
            [
                "核对边界标记",
                "显示候选数据的核验与审核状态。",
                "candidate_data=true；pending_source_lookup；approved_for_rag=false。",
            ],
        ],
        [1900, 3600, 3860],
        font_size=7.8,
        first_col_bold=True,
        spacer_after=False,
    )

    doc.add_heading("期望输出", level=2)
    expected_rows = [
        ["推荐违规类型", "、".join(expected["expected_violation_types"])],
        ["判断理由", expected["human_reason"]],
        ["对应案例", f"{verification['first_hit_title']}（{verification['first_hit_case_id']}）"],
        ["建议检索文本", verification["recommended_query"]],
        [
            "本地实测",
            f"HTTP 200；首条命中；fielded BM25 score={verification['score']:.6f}；"
            f"约 {verification['elapsed_ms']:.2f} ms",
        ],
    ]
    if expected.get("notes"):
        expected_rows.append(["补充说明", expected["notes"]])
    add_table(
        doc,
        ["输出项", "期望值"],
        expected_rows,
        [1900, 7460],
        font_size=7.8,
        first_col_bold=True,
        spacer_after=False,
    )
    limit = doc.add_paragraph()
    limit.paragraph_format.space_before = Pt(5)
    limit.paragraph_format.space_after = Pt(0)
    limit.paragraph_format.line_spacing = 1.05
    label = limit.add_run("使用限制：")
    set_run_font(label, size=7.7, bold=True, color=RED)
    body = limit.add_run(
        "对应案例为 pending_source_lookup / pending_review / approved_for_rag=false。"
        "只验证召回，不得把案例标题、处罚结果或法律依据作为已核实事实对外引用。"
    )
    set_run_font(body, size=7.7, color=INK)


def build_test_guide(selected_cases: list[dict]) -> Path:
    doc = Document()
    configure_document(doc, "评委测试样例（3 条）")
    section = doc.sections[0]
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.header_distance = Inches(0.28)
    section.footer_distance = Inches(0.28)
    for name, before, after in (("Heading 1", 5, 3), ("Heading 2", 3, 2), ("Heading 3", 3, 1)):
        doc.styles[name].paragraph_format.space_before = Pt(before)
        doc.styles[name].paragraph_format.space_after = Pt(after)
    add_title_block(
        doc,
        "Adsure 评委测试样例",
        "3 条完整用例｜美妆、游戏、保健食品各 1 条",
        "Evaluation Pack · v1.0",
    )
    add_callout(
        doc,
        "先读此页",
        f"本包使用 candidate_debug。2026-07-19 在候选索引 {INDEX_VERSION} 上实测：3/3 HTTP 200，3/3 预期候选案例首条命中。美妆、游戏文案由图片人工抽取并标注“（有图片）”；类案仍待来源核验。",
    )
    doc.add_heading("测试总览", level=1)
    summary_rows = []
    for case in selected_cases:
        expected = case["human_reference"]
        verification = RAG_VERIFICATION[case["case_id"]]
        summary_rows.append(
            [
                case["case_id"],
                case["input_payload"]["industry"],
                expected["expected_risk_level"],
                expected["expected_routing"],
                verification["first_hit_case_id"],
                f"{verification['score']:.3f}",
            ]
        )
    add_table(
        doc,
        ["样例 ID", "赛道", "风险", "路由", "首条命中 case_id", "分数"],
        summary_rows,
        [1800, 900, 700, 850, 4200, 910],
        font_size=7.75,
        spacer_after=False,
    )
    doc.add_heading("统一测试方法", level=1)
    add_table(
        doc,
        ["阶段", "操作", "判定"],
        [
            ["审核", "只发送 input_payload；不要发送 human_reference/provenance。", "返回结构完整，风险与路由符合用例。"],
            ["RAG", "候选调试环境向 /cases/retrieve 发送 rag_request；其 content 为场景化检索文本。", "HTTP 200，首条 case_id 与表格一致。"],
            ["边界", "检查案例卡片候选态字段。", "明确提示待来源核验，不对外引用处罚事实。"],
        ],
        [1200, 4680, 3480],
        font_size=8.1,
        first_col_bold=True,
        spacer_after=False,
    )
    add_callout(
        doc,
        "配套文件",
        "Adsure_评委测试样例_3条.json 可复制完整请求；Adsure_评委测试样例_3条_RAG实测记录.json 保存索引、分数和回归测试证据。",
        fill=PALE_GRAY,
        color=DARK_BLUE,
        spacer_after=False,
    )

    for ordinal, case in enumerate(selected_cases, 1):
        add_page_break(doc)
        add_case_detail(doc, ordinal, case)

    out = OUTPUT_DIR / "Adsure_评委测试样例_3条_完整稿.docx"
    doc.save(out)
    return out


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    selected_cases = build_submission_cases()
    handbook = build_handbook()
    package_json, record_json = build_machine_test_pack(selected_cases)
    test_guide = build_test_guide(selected_cases)
    print(handbook)
    print(test_guide)
    print(package_json)
    print(record_json)


if __name__ == "__main__":
    main()
