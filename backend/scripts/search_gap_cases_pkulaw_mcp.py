#!/usr/bin/env python3
"""通过北大法宝案例 MCP 为 8 个广告缺口场景检索司法/行政参考案例。

安全边界：
- Token 只从 PKULAW_MCP_TOKEN 读取，不打印、不落盘；
- 串行访问，默认请求间隔 1.8 秒；
- 每次 MCP 返回的 Data 原样保存到 data/sources/pkulaw_gap_search/<batch>/raw/；
- 法宝案例仅作“司法/行政参考线索”，不自动进入 structured/ 或生产 RAG；
- 行政处罚事实仍须回溯市场监管部门/信用中国等一手公开来源。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
KEYWORD_EP = "https://apim-gateway.pkulaw.com/mcp-case"
SEMANTIC_EP = "https://apim-gateway.pkulaw.com/mcp-case-search-service"

SCENARIOS = [
    {
        "id": "s01_minor_protection",
        "name": "未成年人保护",
        "keyword_queries": [
            {"title": "广告", "fulltext": "未成年人 广告 诱导 消费 处罚"},
            {"title": "广告", "fulltext": "不满十周岁 未成年人 广告代言人"},
            {"title": "", "fulltext": "未成年人 游戏 广告 充值"},
            {"title": "广告", "fulltext": "中小学校 幼儿园 广告 处罚"},
            {"title": "", "fulltext": "儿童 广告 未成年人 消费"},
        ],
        "semantic_queries": [
            "广告诱导未成年人消费、未成年人代言游戏或校园广告引发行政处罚或行政争议的案例",
        ],
        "terms": ["未成年人", "未成年", "不满十周岁", "中小学校", "幼儿园", "小学生", "儿童", "诱导", "游戏充值"],
        "exact_terms": ["未成年人", "不满十周岁", "中小学校", "幼儿园", "小学生", "儿童"],
    },
    {
        "id": "s02_game_license_antiaddiction",
        "name": "版号/防沉迷",
        "keyword_queries": [
            {"title": "", "fulltext": "网络游戏 版号 广告"},
            {"title": "", "fulltext": "网络游戏 防沉迷 实名制 广告"},
            {"title": "", "fulltext": "擅自上网出版网络游戏 行政处罚"},
            {"title": "", "fulltext": "游戏版号 未经审批 网络游戏"},
            {"title": "", "fulltext": "网络游戏 适龄提示 广告 充值"},
        ],
        "semantic_queries": [
            "网络游戏未经审批出版、无版号、未落实防沉迷实名制，同时涉及游戏广告或诱导充值的行政处罚和行政争议案例",
        ],
        "terms": ["版号", "防沉迷", "实名制", "未实名", "网络游戏", "上网出版", "网络出版", "游戏审批", "适龄提示", "游戏广告"],
        "exact_terms": ["版号", "防沉迷", "实名制", "未实名", "上网出版", "网络出版", "游戏审批", "适龄提示"],
    },
    {
        "id": "s03_platform_rules",
        "name": "平台规则类",
        "keyword_queries": [
            {"title": "广告", "fulltext": "直播带货 虚假广告 处罚"},
            {"title": "广告", "fulltext": "小红书 医疗广告 虚假宣传"},
            {"title": "", "fulltext": "抖音 游戏广告 虚假宣传 充值"},
            {"title": "广告", "fulltext": "淘宝 网店 虚假广告"},
            {"title": "广告", "fulltext": "拼多多 网店 广告 处罚"},
            {"title": "广告", "fulltext": "电商平台 信息流广告 虚假宣传"},
        ],
        "semantic_queries": [
            "直播带货、小红书、抖音、淘宝、拼多多等平台网店发布违法广告或虚假宣传引发处罚和行政争议的案例",
        ],
        "terms": ["直播带货", "直播间", "信息流广告", "小红书", "抖音", "天猫", "京东", "淘宝", "拼多多", "网店", "电商", "平台", "短视频", "美团"],
        "exact_terms": ["直播带货", "直播间", "信息流广告", "小红书", "抖音", "天猫", "京东", "淘宝", "拼多多", "网店", "短视频", "美团"],
    },
    {
        "id": "s04_endorsement",
        "name": "广告代言",
        "keyword_queries": [
            {"title": "广告", "fulltext": "广告代言人 推荐 证明 处罚"},
            {"title": "广告", "fulltext": "明星代言 虚假广告 责任"},
            {"title": "广告", "fulltext": "医疗广告 代言人 推荐证明"},
            {"title": "广告", "fulltext": "受益者名义 形象 推荐 证明"},
            {"title": "广告", "fulltext": "网红 推荐官 体验官 代言"},
        ],
        "semantic_queries": [
            "广告代言人、明星网红、推荐官、受益者名义或形象在医疗食品化妆品广告中作推荐证明被处罚或承担责任的案例",
        ],
        "terms": ["代言人", "代言", "明星代言", "网红", "推荐官", "体验官", "推荐、证明", "推荐证明", "受益者", "名义或者形象", "形象作推荐"],
        "exact_terms": ["代言人", "代言", "明星代言", "网红", "推荐官", "体验官", "推荐、证明", "推荐证明", "受益者", "形象作推荐"],
    },
    {
        "id": "s05_edible_cosmetics",
        "name": "化妆品可食用",
        "keyword_queries": [
            {"title": "广告", "fulltext": "化妆品 虚假广告"},
            {"title": "广告", "fulltext": "化妆品 医疗用语"},
            {"title": "化妆品", "fulltext": "广告"},
            {"title": "广告", "fulltext": "化妆品 功效 虚假宣传"},
            {"title": "广告", "fulltext": "润唇膏 广告"},
            {"title": "广告", "fulltext": "儿童化妆品 广告"},
            {"title": "广告", "fulltext": "化妆品 可食用"},
            {"title": "广告", "fulltext": "化妆品 食品级"},
        ],
        "semantic_queries": [
            "化妆品、儿童化妆品、润唇膏宣传可食用、食品级、可以吃，或者把普通化妆品作食品医疗功效宣传的广告处罚案例",
        ],
        "terms": ["可食用", "食品级", "食用级", "可以吃", "可吃", "口服", "儿童化妆品", "润唇膏", "唇膏", "化妆品", "护肤品"],
        "exact_terms": ["可食用", "食品级", "食用级", "可以吃", "可吃", "儿童化妆品", "润唇膏"],
    },
    {
        "id": "s06_gift_promotion",
        "name": "买赠规则",
        "keyword_queries": [
            {"title": "广告", "fulltext": "买一送一 虚假广告 处罚"},
            {"title": "广告", "fulltext": "买赠 赠品 广告 虚假宣传"},
            {"title": "广告", "fulltext": "满减 促销 广告 期限"},
            {"title": "广告", "fulltext": "药品 买5得6 赠送 广告"},
            {"title": "", "fulltext": "促销 赠品 虚假宣传 处罚"},
        ],
        "semantic_queries": [
            "买一送一、买赠、赠品、满减、限时促销广告规则不清、无法兑现或未标明期限引发处罚的案例",
        ],
        "terms": ["买一送一", "买一送", "买赠", "买5得6", "赠品", "满减", "促销", "赠送", "限时立减", "限时特价", "返现", "减价", "折价"],
        "exact_terms": ["买一送一", "买一送", "买赠", "买5得6", "赠品", "满减", "限时立减", "限时特价", "返现", "减价", "折价"],
    },
    {
        "id": "s07_game_cashout",
        "name": "游戏收益/提现",
        "keyword_queries": [
            {"title": "", "fulltext": "游戏广告 提现 收益 日赚"},
            {"title": "", "fulltext": "网络游戏 虚假广告 充值 奖励"},
            {"title": "", "fulltext": "红包版游戏 提现 虚假宣传"},
            {"title": "", "fulltext": "看广告赚钱 游戏 提现"},
            {"title": "", "fulltext": "游戏 诱导充值 广告 处罚"},
        ],
        "semantic_queries": [
            "游戏广告宣称可以提现、日赚、红包收益、升级赚钱，诱导玩家充值但无法兑现，引发处罚、民事或行政争议的案例",
        ],
        "terms": ["提现", "日赚", "收益", "赚钱", "红包", "充值", "诱导充值", "无法兑现", "奖励", "游戏广告", "虚假广告"],
        "exact_terms": ["提现", "日赚", "收益", "赚钱", "红包", "诱导充值", "无法兑现"],
    },
    {
        "id": "s08_data_citation",
        "name": "数据引证",
        "keyword_queries": [
            {"title": "广告", "fulltext": "刷单 虚假宣传"},
            {"title": "广告", "fulltext": "虚构 交易 评价"},
            {"title": "广告", "fulltext": "销售状况 虚假广告"},
            {"title": "广告", "fulltext": "用户评价 虚假广告"},
            {"title": "广告", "fulltext": "引证内容 广告"},
            {"title": "广告", "fulltext": "数据 虚假广告"},
            {"title": "广告", "fulltext": "销量 虚假广告"},
            {"title": "广告", "fulltext": "好评 虚假宣传"},
            {"title": "广告", "fulltext": "成交占比 广告"},
            {"title": "广告", "fulltext": "临床数据 广告"},
        ],
        "semantic_queries": [
            "广告引用销量、好评率、下载量、排名、成交占比、临床数据等没有出处或通过刷单虚构交易和用户评价的处罚案例",
        ],
        "terms": ["好评率", "销量", "销售状况", "下载量", "数据来源", "临床数据", "成交占比", "排名", "销冠", "TOP1", "刷单", "用户评价", "无出处", "虚构", "数据"],
        "exact_terms": ["好评率", "销量", "销售状况", "下载量", "数据来源", "临床数据", "成交占比", "排名", "销冠", "TOP1", "刷单", "用户评价", "无出处"],
    },
]

AD_TERMS = ["广告", "宣传", "推广", "代言", "推荐", "直播", "电商", "网店", "刷单", "促销", "处罚"]
MARKET_TERMS = ["市场监督管理", "市场监管", "工商", "广告法", "反不正当竞争法"]
REMOTE_TERMS = ["市场监督管理局", "工商行政管理", "市场监管"]


@dataclass
class Hit:
    record: dict[str, Any]
    queries: set[str] = field(default_factory=set)
    raw_paths: set[str] = field(default_factory=set)
    score: int = 0
    evidence: list[str] = field(default_factory=list)
    matched_terms: set[str] = field(default_factory=set)


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def compact(s: Any, limit: int = 100000) -> str:
    s = html.unescape(str(s or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s[:limit]


def record_text(r: dict[str, Any]) -> str:
    fields = [
        "Title", "Category", "CaseGrade", "Court", "LastInstanceDate", "CaseFlag",
        "CaseClassName", "TrialStep", "DocumentAttr", "Core", "CaseGist",
        "TrialAfter", "PlaintiffClaims", "DefenseViewpoint", "ControversialFocus",
        "Ascertain", "Identified", "RefereeBasis", "RefereeResult", "Accusation",
    ]
    return "\n".join(compact(r.get(k), 20000) for k in fields)


def url_of(r: dict[str, Any]) -> str:
    m = re.search(r"\((https?://[^)]+)\)", str(r.get("Url") or ""))
    return m.group(1) if m else str(r.get("Url") or "")


def case_id(scenario_id: str, r: dict[str, Any]) -> str:
    seed = r.get("CaseFlag") or r.get("Url") or r.get("Title")
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()[:10]
    return f"pkulaw_gap_{scenario_id}_{digest}"


class PkulawMcp:
    def __init__(self, token: str, delay: float) -> None:
        self.token = token
        self.delay = delay
        self._id = 0
        self.initialized: set[str] = set()

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.token}",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            text = resp.read().decode("utf-8", "replace")
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return json.loads(text)

    def initialize(self, endpoint: str) -> None:
        if endpoint in self.initialized:
            return
        self._id += 1
        self._post(endpoint, {
            "jsonrpc": "2.0", "id": self._id, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "adsure-pkulaw-gap-search", "version": "0.1"}},
        })
        try:
            self._post(endpoint, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except Exception:
            pass
        self.initialized.add(endpoint)

    def call(self, endpoint: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if endpoint not in self.initialized:
            self.initialize(endpoint)
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                self._id += 1
                envelope = self._post(endpoint, {
                    "jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                })
                if envelope.get("error"):
                    return {"_rpc_error": envelope["error"]}
                result = envelope.get("result") or {}
                if result.get("isError"):
                    return {"_tool_error": result.get("content")}
                return json.loads(result["content"][0]["text"])
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_exc = exc
                time.sleep(2.0 + attempt * 2.0)
        return {"_transport_error": f"{type(last_exc).__name__}: {last_exc}"}

    def sleep(self) -> None:
        time.sleep(self.delay)


def safe_name(s: str) -> str:
    return re.sub(r"[^\w一-鿿-]+", "_", s).strip("_")[:80] or "query"


def score_record(scenario: dict[str, Any], r: dict[str, Any]) -> tuple[int, set[str], list[str]]:
    title = compact(r.get("Title"))
    text = record_text(r)
    hay = f"{title}\n{text}"
    score = 0
    matched: set[str] = set()
    evidence: list[str] = []

    for term in scenario["terms"]:
        if term and term.lower() in hay.lower():
            matched.add(term)
            score += 4 if term in scenario["exact_terms"] else 2
            if term in title:
                score += 8
            idx = hay.lower().find(term.lower())
            snippet = hay[max(0, idx - 70): idx + len(term) + 100]
            evidence.append(re.sub(r"\s+", " ", snippet).strip())
    if not matched:
        return 0, matched, []

    if any(t in hay for t in AD_TERMS):
        score += 8
    if any(t in hay for t in MARKET_TERMS):
        score += 8
    cats = " ".join(r.get("Category") or [])
    if "行政" in cats or "行政" in title:
        score += 12
    if "民事" in cats or "民事" in title:
        score += 2
    if "刑事" in cats or "刑初" in (r.get("CaseFlag") or ""):
        score -= 8

    # 场景专属校准：避免“促销/数据”等通用词把无关案件带入。
    sid = scenario["id"]
    exact_hits = matched & set(scenario["exact_terms"])
    if sid == "s05_edible_cosmetics":
        cosmetic_context = bool(re.search(r"化妆品|护肤品|润唇膏|唇膏|美容|医美|口腔清洁|洗护", hay))
        if not cosmetic_context:
            return 0, set(), []
        if exact_hits & {"可食用", "食品级", "食用级", "可以吃", "可吃", "儿童化妆品", "润唇膏"}:
            score += 18
        elif any(t in hay for t in ["虚假广告", "广告法", "虚假宣传", "医疗用语", "功效"]):
            score += 6  # 化妆品广告相邻线索，低于可食用强匹配
        else:
            score -= 15
    if sid == "s06_gift_promotion" and not exact_hits:
        score -= 15
    if sid == "s07_game_cashout" and not re.search(r"游戏|广告|充值|红包", hay):
        score -= 30
    if sid == "s02_game_license_antiaddiction" and not re.search(r"网络游戏|游戏|网络出版", hay):
        score -= 30
    if sid == "s01_minor_protection" and not re.search(r"未成年|儿童|小学生|幼儿园|中小学校", hay):
        score -= 30
    if sid == "s08_data_citation" and not re.search(r"广告|宣传|刷单|用户评价|销售状况", hay):
        score -= 20

    # 去重证据，保留短片段供人快速判断。
    dedup = []
    for e in evidence:
        if e not in dedup:
            dedup.append(e)
    return score, matched, dedup[:5]


def relevance_level(scenario_id: str, r: dict[str, Any], matched_terms: set[str]) -> str:
    text = record_text(r)
    if scenario_id == "s05_edible_cosmetics":
        if matched_terms & {"可食用", "食品级", "食用级", "可以吃", "可吃", "儿童化妆品", "润唇膏"}:
            return "strong_specific_match"
        return "adjacent_cosmetic_advertising_case"
    if scenario_id == "s02_game_license_antiaddiction" and matched_terms & {"版号", "防沉迷", "实名制", "未实名", "上网出版", "网络出版", "游戏审批", "适龄提示"}:
        return "strong_specific_match"
    if scenario_id == "s07_game_cashout" and re.search(r"游戏", text) and matched_terms & {"提现", "日赚", "收益", "赚钱", "红包", "诱导充值", "无法兑现"}:
        return "strong_specific_match"
    return "strong_specific_match" if matched_terms else "adjacent_reference"

def classify_reference(r: dict[str, Any]) -> str:
    cats = " ".join(r.get("Category") or [])
    title = compact(r.get("Title"))
    text = record_text(r)
    if "行政" in cats or "行政" in title:
        if any(t in text for t in REMOTE_TERMS):
            return "administrative_penalty_judicial_review_reference"
        return "administrative_other_reference"
    if "刑事" in cats:
        return "criminal_reference"
    return "civil_judicial_reference"


def write_raw(out_dir: Path, prefix: str, query_label: str, request_args: dict, payload: dict) -> Path:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{prefix}__{safe_name(query_label)}.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    envelope = {
        "fetched_at": now_iso(),
        "source_name": "北大法宝（pkulaw.com，经 MCP 检索）",
        "tool": prefix,
        "request_arguments": request_args,
        "sha256": hashlib.sha256(body).hexdigest(),
        "response": payload,
    }
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="20260917")
    ap.add_argument("--target-per-scenario", type=int, default=12)
    ap.add_argument("--delay", type=float, default=1.8)
    ap.add_argument("--keyword-only", action="store_true")
    ap.add_argument("--scenarios", default="", help="逗号分隔场景 id；默认全部")
    args = ap.parse_args()

    token = os.environ.get("PKULAW_MCP_TOKEN", "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        sys.exit("PKULAW_MCP_TOKEN 未设置")

    out_dir = ROOT / "data/sources/pkulaw_gap_search" / args.batch
    report_dir = ROOT / "data/reports/source_verification"
    report_dir.mkdir(parents=True, exist_ok=True)
    client = PkulawMcp(token, args.delay)
    query_log: list[dict[str, Any]] = []
    hits: dict[str, dict[str, Hit]] = {s["id"]: {} for s in SCENARIOS}

    def absorb(scenario: dict[str, Any], payload: dict, label: str, raw_path: Path, tool: str) -> None:
        records = payload.get("Data") if isinstance(payload, dict) else None
        query_log.append({
            "scenario_id": scenario["id"], "scenario": scenario["name"], "tool": tool,
            "query": label, "total": payload.get("Total") if isinstance(payload, dict) else None,
            "returned": len(records or []), "raw_path": str(raw_path.relative_to(ROOT)),
            "error": payload.get("_rpc_error") or payload.get("_transport_error") or payload.get("_tool_error") or "",
        })
        for r in records or []:
            key = str(r.get("CaseFlag") or r.get("Url") or r.get("Title"))
            score, terms, evidence = score_record(scenario, r)
            if score <= 0:
                continue
            h = hits[scenario["id"]].setdefault(key, Hit(record=r))
            h.queries.add(label)
            h.raw_paths.add(str(raw_path.relative_to(ROOT)))
            h.evidence.extend(evidence)
            h.matched_terms.update(terms)
            h.score = max(h.score, score)

    selected_scenarios = [x for x in SCENARIOS if not args.scenarios or x["id"] in {v.strip() for v in args.scenarios.split(",") if v.strip()}]
    for scenario in selected_scenarios:
        for i, q in enumerate(scenario["keyword_queries"], 1):
            arguments = {"documentAttr": ["判决书", "裁定书"], **q}
            label = f"kw{i}_{q.get('title') or 'no_title'}_{q.get('fulltext')}"
            payload = client.call(KEYWORD_EP, "get_case_list", arguments)
            raw_path = write_raw(out_dir, "get_case_list", f"{scenario['id']}__{label}", arguments, payload)
            absorb(scenario, payload, label, raw_path, "get_case_list")
            client.sleep()
        if not args.keyword_only and len(hits[scenario["id"]]) < args.target_per_scenario:
            for i, text in enumerate(scenario["semantic_queries"], 1):
                arguments = {"text": text, "size": 20}
                label = f"sem{i}_{text}"
                payload = client.call(SEMANTIC_EP, "search_case", arguments)
                raw_path = write_raw(out_dir, "search_case", f"{scenario['id']}__{label}", arguments, payload)
                absorb(scenario, payload, label, raw_path, "search_case")
                client.sleep()

    selected_rows = []
    coverage = {}
    for scenario in SCENARIOS:
        ordered = sorted(hits[scenario["id"]].values(), key=lambda h: (h.score, h.record.get("LastInstanceDate") or ""), reverse=True)
        chosen = ordered[:args.target_per_scenario]
        coverage[scenario["id"]] = {
            "name": scenario["name"], "unique_relevant_hits": len(ordered),
            "selected": len(chosen), "target": args.target_per_scenario,
            "meets_target": len(chosen) >= args.target_per_scenario,
        }
        for rank, h in enumerate(chosen, 1):
            r = h.record
            cid = case_id(scenario["id"], r)
            row = {
                "case_id": cid,
                "scenario_id": scenario["id"],
                "scenario_name": scenario["name"],
                "scenario_rank": rank,
                "relevance_score": h.score,
                "reference_classification": classify_reference(r),
                "relevance_level": relevance_level(scenario["id"], r, h.matched_terms),
                "title": r.get("Title") or "",
                "case_number": r.get("CaseFlag") or "",
                "court": r.get("Court") or "",
                "decision_date": (r.get("LastInstanceDate") or "").replace(".", "-"),
                "document_attr": r.get("DocumentAttr") or [],
                "category": r.get("Category") or [],
                "case_class_name": r.get("CaseClassName") or "",
                "source_name": "北大法宝（pkulaw.com，经 MCP 检索）",
                "source_url": url_of(r),
                "source_tier_note": "第三方法律数据库司法案例/行政裁判线索；不是行政机关一手处罚事实，入规则RAG前必须回溯官方处罚决定书。",
                "matched_terms": sorted(h.matched_terms),
                "evidence_snippets": h.evidence[:3],
                "referee_basis": compact(r.get("RefereeBasis"), 1200),
                "referee_result": compact(r.get("RefereeResult"), 1200),
                "identified_excerpt": compact(r.get("Identified") or r.get("Ascertain") or r.get("TrialAfter"), 1800),
                "queries": sorted(h.queries),
                "raw_text_paths": sorted(h.raw_paths),
                "review_status": "pending_human_review",
                "approved_for_rag": False,
            }
            selected_rows.append(row)

    manifest = {
        "generated_at": now_iso(),
        "batch": args.batch,
        "target_per_scenario": args.target_per_scenario,
        "compliance": {
            "serial_requests": True,
            "default_delay_seconds": args.delay,
            "token_not_written": True,
            "pku_law_reference_only": True,
            "not_promoted_to_production_rag": True,
        },
        "coverage": coverage,
        "queries": query_log,
        "rows": selected_rows,
    }
    json_path = report_dir / f"pkulaw_gap_case_search_{args.batch}.json"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = report_dir / f"pkulaw_gap_case_search_{args.batch}.csv"
    fields = ["case_id", "scenario_id", "scenario_name", "scenario_rank", "relevance_score", "reference_classification", "relevance_level", "title", "case_number", "court", "decision_date", "case_class_name", "source_url", "matched_terms", "raw_text_paths", "review_status"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in selected_rows:
            out = {k: row.get(k, "") for k in fields}
            for k in ["document_attr", "category", "matched_terms", "raw_text_paths"]:
                if isinstance(out.get(k), list):
                    out[k] = ";".join(out[k])
            w.writerow(out)

    lines = ["# 北大法宝 MCP：8 个广告缺口场景案例线索", "", f"- 批次：{args.batch}；每场景目标：{args.target_per_scenario} 条", "- 用途：司法/行政参考线索；不作为行政处罚事实直接进入生产 RAG。", "", "| 场景 | 相关唯一案例 | 已选 | 是否达标 |", "|---|---:|---:|---|"]
    for sid, c in coverage.items():
        lines.append(f"| {c['name']} | {c['unique_relevant_hits']} | {c['selected']} | {'是' if c['meets_target'] else '否'} |")
    lines.append("")
    for scenario in selected_scenarios:
        rows = [x for x in selected_rows if x["scenario_id"] == scenario["id"]]
        lines += [f"## {scenario['name']}", ""]
        for x in rows:
            lines.append(f"{x['scenario_rank']}. [{x['title']}]({x['source_url']})；{x['court']}；{x['case_number']}；{x['decision_date']}；`{x['reference_classification']}`；匹配：{'、'.join(x['matched_terms'])}")
            lines.append(f"   - 证据：`{x['raw_text_paths'][0]}`；人审状态：`pending_human_review`")
        lines.append("")
    md_path = report_dir / f"pkulaw_gap_case_search_{args.batch}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"coverage": coverage, "rows": len(selected_rows), "json": str(json_path), "csv": str(csv_path), "md": str(md_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
