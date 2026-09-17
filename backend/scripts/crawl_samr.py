# -*- coding: utf-8 -*-
"""抓取市场监管总局典型案例通报，入候选库。

    python backend/scripts/crawl_samr.py [--pages N] [--limit N] [--dry-run]

约束（不可通过参数放宽）：
  · robots.txt 硬门禁
  · 对同一站点的请求间隔 ≥3 秒 —— 这是对站点的礼貌，与我们要多少条无关
  · 产出一律进 structured_candidates，永不自动进 structured

可通过参数放宽（且会在日志里留痕）：
  · --cases-per-hour：每小时入库条数上限，默认 100。它约束的是**人工复核产能**，
    不是站点负载，所以和请求间隔是两个独立的旋钮，不要混为一谈。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.crawler.fetch import Fetcher
from app.crawler.parsers import Link, parse_samr_api, samr_list_urls
from app.crawler.pipeline import CrawlPipeline, Outcome
from app.crawler.policy import RateLimiter, RobotsGate
from app.reasoning.subsume import get_llm_provider

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "data"

logging.basicConfig(level=logging.WARNING,
                    format="%(levelname)s %(name)s: %(message)s")


def case_id_from(url: str) -> str:
    """用详情页 URL 的 hash 段做 case_id —— 稳定、可回溯、天然不重复。"""
    stem = url.rstrip("/").split("/")[-1].replace(".html", "")
    return f"samr_{stem[-12:]}"


def _load_source_config(source_id: str) -> dict | None:
    """从 backend/app/crawler/sources.yaml 读取指定源的配置。"""
    import yaml
    cfg_path = Path(__file__).resolve().parent.parent / "app" / "crawler" / "sources.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    for src in data.get("sources", []):
        if src.get("id") == source_id:
            return src
    return None


def _enabled_source_ids() -> list[str]:
    import yaml
    cfg_path = Path(__file__).resolve().parent.parent / "app" / "crawler" / "sources.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return [src["id"] for src in data.get("sources", [])
            if src.get("enabled") and src.get("parser")]


def _allowed_hosts_for(source_id: str) -> set[str]:
    from urllib.parse import urlparse
    if source_id == "samr":
        return {"www.samr.gov.cn", "samr.gov.cn"}
    cfg = _load_source_config(source_id) or {}
    base = cfg.get("base_url") or cfg.get("list_url") or ""
    host = (urlparse(base).hostname or "").lower()
    if not host:
        return {"www.samr.gov.cn", "samr.gov.cn"}
    hosts = {host}
    hosts.add(host[4:] if host.startswith("www.") else f"www.{host}")
    return hosts


def _discover(source_id: str, args, fetcher) -> list[Link]:
    links: list[Link] = []
    if source_id == "samr":
        for n, lu in enumerate(samr_list_urls(args.pages), start=1):
            try:
                page = fetcher.fetch(lu)
            except Exception as exc:
                print(f"  第 {n} 页抓取失败：{exc}")
                continue
            found = parse_samr_api(page.raw_html)
            print(f"  第 {n} 页 → {len(found)} 条相关")
            links.extend(found)
        return links

    cfg = _load_source_config(source_id)
    if cfg is None:
        print(f"⛔ sources.yaml 中未找到源「{source_id}」，无法抓取。")
        return links
    if not cfg.get("enabled") or not cfg.get("list_url"):
        print(f"⛔ 源「{source_id}」未启用或 list_url 未确认（enabled={cfg.get('enabled')}, "
              f"list_url={cfg.get('list_url')}）。启用步骤见 parsers.py/sources.yaml。")
        return links
    parser = cfg.get("parser", "")
    if parser == "local_samr":
        from app.crawler.parsers import local_samr_list_urls, parse_local_samr_list
        list_urls = local_samr_list_urls(cfg["list_url"], args.pages)
        parse_list = parse_local_samr_list
    elif parser == "shanghai_zfxxgkml":
        from app.crawler.parsers import shanghai_list_urls, parse_shanghai_zfxxgkml
        list_urls = shanghai_list_urls(args.pages)
        parse_list = parse_shanghai_zfxxgkml
    elif parser == "nppa_tzgs":
        from app.crawler.parsers import nppa_list_urls, parse_nppa_tzgs
        list_urls = nppa_list_urls(args.pages)
        parse_list = parse_nppa_tzgs
    elif parser == "creditchina":
        from app.crawler.parsers import creditchina_list_urls, parse_creditchina_list
        list_urls = creditchina_list_urls(cfg["list_url"], args.pages)
        parse_list = parse_creditchina_list
    else:
        print(f"⛔ 未实现的 parser：{parser}。")
        return links
    if not list_urls:
        print(f"⛔ 源「{source_id}」未配置 list_url，无法构造列表页。")
        return links
    for n, lu in enumerate(list_urls, start=1):
        try:
            page = fetcher.fetch(lu)
        except Exception as exc:
            print(f"  第 {n} 页抓取失败：{exc}")
            continue
        found = parse_list(page.raw_html, lu)  # 相对 href 以当前列表页为基址
        print(f"  第 {n} 页 → {len(found)} 条处罚链接")
        links.extend(found)
    return links


def _crawl_source(source_id: str, args, limiter) -> None:
    fetcher = Fetcher(gate=RobotsGate(), limiter=limiter,
                      allowed_hosts=_allowed_hosts_for(source_id))
    links = _discover(source_id, args, fetcher)
    html_dir = DATA_DIR / "raw_html"
    seen, uniq, skipped = set(), [], 0
    for l in links:
        if l.url in seen:
            continue
        seen.add(l.url)
        if args.skip_crawled and (html_dir / f"{case_id_from(l.url)}.html").exists():
            skipped += 1
            continue
        uniq.append(l)
    if skipped:
        print(f"  跳过 {skipped} 个已抓过的详情页")
    uniq = uniq[: args.limit]
    print(f"\n共 {len(uniq)} 个详情页待处理：")
    for l in uniq:
        print(f"  · {l.title[:56]}")
    if args.dry_run:
        print("\n[dry-run] 未实际抓取。")
        return
    if not uniq:
        print("\n没有找到相关链接，结束。")
        return
    _run(uniq, fetcher, limiter, args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=str,
                    choices=["samr", "local_samr", "creditchina", "nppa", "all"],
                    default="samr",
                    help="数据源：samr=总局典型案例(P0)；local_samr=地方市监局(P1)；"
                         "creditchina=信用中国(P2)；all=全部已启用源依次抓取")
    ap.add_argument("--seed", type=str, default=None,
                    help="种子文件（浏览器采集的详情页链接）")
    ap.add_argument("--pages", type=int, default=2, help="扫描多少页列表")
    ap.add_argument("--limit", type=int, default=8, help="最多处理多少个详情页")
    ap.add_argument("--cases-per-hour", type=int, default=100,
                    help="每小时入库上限（人工复核产能，与请求间隔无关）")
    ap.add_argument("--skip-crawled", action="store_true",
                    help="跳过已抓过的详情页（按 raw_html 里的落盘记录判断）")
    ap.add_argument("--dry-run", action="store_true", help="只列出将抓的链接，不抓")
    ap.add_argument("--auto-promote", action="store_true",
                    help="落地后自动把官方广告相关案例转入正式库（结构化+重建索引）")
    ap.add_argument("--llm", choices=["mock", "deepseek"], default="mock",
                    help="结构化抽取后端；默认 mock 只用于安全联调，不产生可用候选")
    args = ap.parse_args()

    if args.cases_per_hour != 100:
        print(f"⚠️ 入库上限已从默认 100 调整为 {args.cases_per_hour} 条/小时。"
              f"请求间隔仍为 3 秒，未放宽。")

    limiter = RateLimiter(cases_per_hour=args.cases_per_hour,
                          min_request_interval=3.0,
                          quota_state_path=DATA_DIR / "ingest_runs" / "crawler_quota.json")

    if args.seed:
        seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
        uniq = [Link(i["url"], i.get("title", "")) for i in seed["items"]][: args.limit]
        print(f"从种子文件载入 {len(uniq)} 个详情页（采集于 {seed.get('collected_at')}）")
        for l in uniq:
            print(f"  · {l.title[:56]}")
        if args.dry_run:
            print("\n[dry-run] 未实际抓取。")
            return
        _run(uniq, Fetcher(gate=RobotsGate(), limiter=limiter,
                            allowed_hosts={"www.samr.gov.cn", "samr.gov.cn"}),
             limiter, args)
    else:
        source_ids = ([args.source] if args.source != "all"
                      else ["samr"] + [i for i in _enabled_source_ids() if i != "samr"])
        for sid in source_ids:
            print("\n" + "=" * 72)
            print(f"数据源：{sid}")
            _crawl_source(sid, args, limiter)

    if args.auto_promote:
        from datetime import datetime, timezone, timedelta
        from app.crawler.promote import promote_landed, rebuild_production
        now = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
        owner = "项目负责人（用户指令：crawler 自动入库）"
        promoted = promote_landed(DATA_DIR, owner, now)
        print(f"\n自动入库：转入正式库 {len(promoted)} 条")
        for cid in promoted:
            print(f"  ✓ {cid}")
        if promoted:
            print("重建生产索引…")
            rebuild_production()
            print("索引已重建。")
        else:
            print("没有新的广告相关官方案例需要自动入库。")
    else:
        print("\n⚠️ 全部产出为待复核候选，未进入正式案例库。")


def _run(uniq, fetcher, limiter, args) -> None:
    llm = get_llm_provider(args.llm)
    if args.llm == "mock":
        print("⚠️ 当前使用 mock：只验证抓取、存证与失败边界，不会生成可用结构化候选。")
    pipe = CrawlPipeline(llm=llm, data_dir=DATA_DIR,
                         fetcher=fetcher, limiter=limiter)
    existing = pipe.load_existing()
    print(f"\n已载入 {existing} 条既有案例用于去重")
    print(f"本小时剩余配额：{limiter.remaining_quota()} 条\n")

    report = pipe.run([(l.url, case_id_from(l.url)) for l in uniq],
                      source_name="国家市场监督管理总局")

    print("=" * 72)
    print(report.summary())
    print("=" * 72)

    by_outcome: dict[str, int] = {}
    for r in report.results:
        by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1

    landed = [r for r in report.results if r.outcome == Outcome.LANDED]
    if landed:
        print(f"\n新入库 {len(landed)} 条（全部为 pending_review，待人工复核）：")
        for r in landed[:15]:
            f = DATA_DIR / "structured_candidates" / f"{r.case_id}.json"
            if not f.exists():
                continue
            c = json.loads(f.read_text(encoding="utf-8"))
            amt = c.get("penalty_amount")
            print(f"  {c.get('segment_title') or c.get('title') or c['case_id']}")
            print(f"     {c.get('party_name','—')} · {c.get('penalty_authority','—')}"
                  f" · {f'{amt:,}元' if amt else '金额未抽出'}")
        if len(landed) > 15:
            print(f"  …… 另有 {len(landed) - 15} 条")

    flagged = [r for r in report.results if r.issues and r.outcome == Outcome.LANDED]
    if flagged:
        print(f"\n带标记待人工留意 {len(flagged)} 条：")
        for r in flagged[:8]:
            print(f"  {r.case_id}: {r.issues[0][:80]}")

    print(f"\n{getattr(llm, 'usage_summary', lambda: '')()}")
    print(f"剩余配额：{limiter.remaining_quota()} 条")

    print("\n⚠️ 本轮产出为待复核候选；自动入库由主流程在全部源跑完后统一执行。")


if __name__ == "__main__":
    main()
