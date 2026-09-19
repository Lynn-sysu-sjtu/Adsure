#!/usr/bin/env python3
"""离线汇总 8 个广告处罚缺口检索结果，并区分行政处罚事实与司法/行政参考。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = ROOT / "data/reports/source_verification"
BATCH = "gap_20260917"
MANIFEST = REPORT_DIR / f"zj_gap_case_search_{BATCH}.json"
DETAIL_DIR = ROOT / f"data/raw_text/zj_xzcf/{BATCH}/detail"
PKULAW_RAW_DIR = ROOT / "data/sources/pkulaw_backfill/full_20260917/raw"

SCENARIOS = [
    ("s01_minor_protection", "未成年人保护"),
    ("s02_game_license_antiaddiction", "版号/防沉迷"),
    ("s03_platform_rules", "平台规则类"),
    ("s04_endorsement", "广告代言"),
    ("s05_edible_cosmetics", "化妆品可食用"),
    ("s06_gift_promotion", "买赠规则"),
    ("s07_game_cashout", "游戏收益/提现"),
    ("s08_data_citation", "数据引证"),
]

ZJ_CROSS_REFERENCES = [
    ("6c0823b6-fdd4-474f-a8a2-7937b74bba6c", "s02_game_license_antiaddiction", "未经批准擅自上网出版网络游戏；文旅部门行政处罚，不是广告处罚事实。"),
    ("46a5cde0-6820-4bb4-a2f4-fde5069e692c", "s02_game_license_antiaddiction", "未经批准擅自上网出版网络游戏；文旅部门行政处罚，不是广告处罚事实。"),
    ("4fd8a5b7-7255-4ef0-b20c-fce893ad83cb", "s02_game_license_antiaddiction", "未经审批擅自上网出版含境外授权网络游戏；文旅部门行政处罚，不是广告处罚事实。"),
    ("88858ca4-8e13-4f41-9b5e-440906eadfe6", "s02_game_license_antiaddiction", "未经批准出版网络游戏；决定书载明游戏内有广告推广模块，但处罚基础仍是网络出版审批，不是广告处罚事实。"),
]

PKULAW_REFERENCES = [
    ("(2023)粤0192民初1448号", ["s02_game_license_antiaddiction", "s03_platform_rules", "s06_gift_promotion"], "抖音游戏广告、版号争议、充值赠品表述不清；民事判决，且当事人称曾有市场监管处罚，需另查一手处罚决定书。"),
    ("(2023)赣1104民初2952号", ["s03_platform_rules", "s07_game_cashout"], "玩家主张抖音游戏广告虚假、诱导充值；民事判决，不是行政处罚事实。"),
    ("(2024)浙0192民初1779号", ["s02_game_license_antiaddiction", "s07_game_cashout"], "网络游戏/平台规则、抽奖概率与可变现饰品争议；民事判决，不是行政处罚事实。"),
    ("(2025)粤0192民初9279号", ["s03_platform_rules", "s07_game_cashout"], "抖音游戏广告承诺充值赠送道具引发民事争议；不是行政处罚事实。"),
    ("(2023)琼96民终6628号", ["s07_game_cashout"], "游戏宣传与充值争议的二审民事判决；不是行政处罚事实。"),
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def detail_doc(guid: str) -> dict:
    p = DETAIL_DIR / f"{guid}.json"
    doc = load_json(p)
    return (doc.get("response") or doc)["data"]["punish"]


def pkulaw_doc(case_flag: str) -> tuple[dict, Path]:
    wanted = re.sub(r"[\s()（）]", "", case_flag)
    for path in PKULAW_RAW_DIR.glob("*.json"):
        try:
            record = load_json(path).get("record") or {}
        except Exception:
            continue
        got = re.sub(r"[\s()（）]", "", record.get("CaseFlag") or "")
        if got == wanted:
            return record, path
    raise FileNotFoundError(case_flag)


def pkulaw_url(record: dict) -> str:
    m = re.search(r"\((https?://[^)]+)\)", record.get("Url") or "")
    return m.group(1) if m else ""


def scenario_rows(manifest: dict) -> dict[str, list[dict]]:
    rows = {sid: [] for sid, _ in SCENARIOS}
    for row in manifest["confirmed_rows"]:
        for sid in row["scenarios"]:
            rows.setdefault(sid, []).append(row)
    return rows


def build_reference_leads(manifest: dict) -> dict:
    zj_refs = []
    for guid, sid, note in ZJ_CROSS_REFERENCES:
        try:
            p = DETAIL_DIR / f"{guid}.json"
            x = detail_doc(guid)
            zj_refs.append({
                "reference_type": "cross_department_administrative_reference",
                "scenario_id": sid,
                "title": x.get("xzcfws_name"),
                "case_number": x.get("xzcfws_code"),
                "authority": x.get("orgnode"),
                "decision_date": x.get("xzcf_date"),
                "party_name": x.get("bxzcf_name"),
                "source_url": f"https://xzcf.zjzwfw.gov.cn/punishment/#/punishdetails?guid={guid}&unid={x.get('unid') or guid}",
                "raw_text_path": str(p.relative_to(ROOT)),
                "note": note,
                "use_boundary": "仅作司法/行政参考，不作为市场监管广告处罚事实入规则 RAG。",
            })
        except FileNotFoundError:
            continue

    pkulaw_refs = []
    for flag, sids, note in PKULAW_REFERENCES:
        try:
            r, path = pkulaw_doc(flag)
            pkulaw_refs.append({
                "reference_type": "pkulaw_judicial_reference",
                "scenario_ids": sids,
                "title": r.get("Title"),
                "case_number": r.get("CaseFlag"),
                "court": r.get("Court"),
                "decision_date": (r.get("LastInstanceDate") or "").replace(".", "-"),
                "source_name": "北大法宝（pkulaw.com，经 MCP 既有回传）",
                "source_url": pkulaw_url(r),
                "raw_text_path": str(path.relative_to(ROOT)),
                "note": note,
                "use_boundary": "司法案例仅作口径参考，不等同于行政处罚事实；需另核行政机关一手处罚决定书。",
            })
        except FileNotFoundError:
            continue

    return {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "pkulaw_mcp_status": {
            "checked_at": "2026-09-17",
            "keyword_endpoint": "HTTP 401 / code 90002: remaining points check failed",
            "semantic_endpoint": "HTTP 401 / code 90002: remaining points check failed",
            "note": "未新增在线法宝结果；本文件仅使用此前经北大法宝 MCP 回传并已落盘的本地证据。",
        },
        "official_administrative_candidate_count": len(manifest["confirmed_rows"]),
        "zj_cross_department_references": zj_refs,
        "pkulaw_judicial_references": pkulaw_refs,
    }


def main() -> None:
    manifest = load_json(MANIFEST)
    rows_by_scenario = scenario_rows(manifest)
    refs = build_reference_leads(manifest)
    refs_path = REPORT_DIR / f"gap_case_reference_leads_{BATCH}.json"
    refs_path.write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8")

    query_terms = {sid: [] for sid, _ in SCENARIOS}
    zero_terms = {sid: [] for sid, _ in SCENARIOS}
    for q in manifest.get("queries", []):
        sid = q.get("scenario_id")
        if sid not in query_terms:
            continue
        term = f"{q.get('keyword')}({q.get('total')})"
        query_terms[sid].append(term)
        if q.get("total") == 0:
            zero_terms[sid].append(q.get("keyword"))

    lines = [
        "# 8 个广告缺口场景案例检索与可用性评估",
        "",
        "## 结论",
        "",
        f"- 浙江 P1 行政处罚结果公开 API：列表去重 {manifest['unique_list_hits']} 条，全文详情 {manifest['detail_targets']} 份，确认市场监管广告/促销处罚候选 {manifest['confirmed_rows'] if False else len(manifest['confirmed_rows'])} 条。",
        "- 所有确认记录均写入 `data/structured_candidates/`，状态为 `pending_human_review`、`approved_for_rag=false`，未进入生产 RAG。",
        "- 每条候选均保留浙江公开 `source_url` 与详情 JSON 的 `raw_text_path`。",
        "- 北大法宝案例关键词/语义 MCP 在 2026-09-17 复查时均返回 HTTP 401 / code 90002（remaining points check failed）；本报告仅复用此前已落盘的法宝 MCP 回传作为司法/行政参考。",
        "",
        "## 分场景覆盖",
        "",
        "| 场景 | 浙江 P1 处罚候选 | 结论 |",
        "|---|---:|---|",
    ]
    for sid, name in SCENARIOS:
        rows = rows_by_scenario.get(sid, [])
        if rows:
            conclusion = f"已入候选 {len(rows)} 条，待人核。"
        elif sid == "s02_game_license_antiaddiction":
            conclusion = "未确认到市场监管广告处罚；有文旅部门擅自上网出版网络游戏行政参考。"
        elif sid == "s05_edible_cosmetics":
            conclusion = "可食用/食品级化妆品强检索与通用兜底未确认到浙江 P1 广告处罚。"
        elif sid == "s07_game_cashout":
            conclusion = "未确认到浙江 P1 游戏提现/收益广告处罚；有相关民事司法参考。"
        else:
            conclusion = "本轮未确认到浙江 P1 强匹配。"
        lines.append(f"| {name} | {len(rows)} | {conclusion} |")

    lines += ["", "## 已确认的浙江行政处罚候选", ""]
    for sid, name in SCENARIOS:
        rows = rows_by_scenario.get(sid, [])
        lines.append(f"### {name}")
        if not rows:
            lines.append("- 无市场监管广告处罚候选。")
        for r in rows:
            lines.append(
                f"- `{r['case_id']}` [{r['title']}]({r['source_url']})；"
                f"{r['authority']}；{r['decision_date']}；罚款 {r.get('amount')}；"
                f"候选：`{r['candidate_path']}`；原文：`{r['raw_text_path']}`"
            )
        lines.append("")

    lines += ["## 零命中强场景词（浙江案名检索）", ""]
    for sid, name in SCENARIOS:
        terms = "、".join(zero_terms.get(sid) or []) or "（无零命中词）"
        lines.append(f"- **{name}**：{terms}")

    lines += ["", "## 司法/跨部门行政参考（不得作为市场监管广告处罚事实）", ""]
    lines.append("### 浙江跨部门行政参考：版号/网络出版")
    for r in refs["zj_cross_department_references"]:
        lines.append(
            f"- [{r['title']}]({r['source_url']})；{r['authority']}；{r['decision_date']}；"
            f"{r['note']} 原文：`{r['raw_text_path']}`"
        )
    lines.append("")
    lines.append("### 北大法宝本地 MCP 回传：游戏/平台民事司法口径")
    for r in refs["pkulaw_judicial_references"]:
        lines.append(
            f"- [{r['title']}]({r['source_url']})；{r['court']}；{r['case_number']}；{r['decision_date']}；"
            f"{r['note']} 本地证据：`{r['raw_text_path']}`"
        )

    lines += [
        "",
        "## 人审重点",
        "",
        "1. `zj_gap_331004082026050004` 案名含未成年人代言表述，但详情正文仅载明“电商平台发布虚假广告”，本轮未映射未成年人/代言场景。",
        "2. 多条决定书同时包含产品质量、药品经营或广告违法，RAG 入库前应只引用与广告/促销违法直接对应的分项罚款和事实。",
        "3. 买赠药品、促销期限类案例依据广告审查规章或促销/价格规则，不应与《广告法》虚假广告罚则混同。",
        "4. 版号/防沉迷、游戏提现、可食用化妆品仍需继续查总局/其他省市监 P0/P1 或信用中国 P2；不得用民事判决替代处罚事实。",
    ]

    out = REPORT_DIR / f"gap_case_search_assessment_{BATCH}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"assessment": str(out), "reference_leads": str(refs_path), "candidates": len(manifest["confirmed_rows"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
