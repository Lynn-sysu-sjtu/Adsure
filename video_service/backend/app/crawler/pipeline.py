"""抓取编排：URL → 抓取 → 抽取 → 校验 → 去重 → 落候选库。

**这条管道的终点是 structured_candidates，永远不是 structured。**
自动化只负责把候选送到人面前，不负责替人拍板。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.crawler.extract import Extractor, to_case
from app.crawler.fetch import Fetcher
from app.crawler.policy import RateLimiter, RobotsDenied, RobotsGate
from app.crawler.quality import DedupIndex, Severity, validate_case
from app.crawler.relevance import tag_case
from app.crawler.segment import split_cases

logger = logging.getLogger(__name__)

SOURCES_PATH = Path(__file__).parent / "sources.yaml"


class Outcome:
    LANDED = "landed"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    ROBOTS_DENIED = "robots_denied"
    FETCH_FAILED = "fetch_failed"
    EXTRACT_FAILED = "extract_failed"
    QUOTA_EXHAUSTED = "quota_exhausted"


@dataclass
class ItemResult:
    url: str
    outcome: str
    case_id: str | None = None
    issues: list[str] = field(default_factory=list)
    dropped_fields: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        tail = f" · {'; '.join(self.issues)}" if self.issues else ""
        return f"[{self.outcome}] {self.url}{tail}"


@dataclass
class RunReport:
    results: list[ItemResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def count(self, outcome: str) -> int:
        return sum(1 for r in self.results if r.outcome == outcome)

    @property
    def landed(self) -> int:
        return self.count(Outcome.LANDED)

    @property
    def extraction_success_rate(self) -> float:
        """抽取成功率。**掉下去就该停** —— 多半是站点改版让解析器失效了，
        继续跑只会产出一堆垃圾候选，把人工复核的时间浪费光。"""
        attempted = [r for r in self.results
                     if r.outcome not in (Outcome.ROBOTS_DENIED, Outcome.QUOTA_EXHAUSTED)]
        if not attempted:
            # 无待抽取项（如配额耗尽/robots 全拒）≠ 抽取失败，按 100% 计
            return 1.0
        ok = sum(1 for r in attempted
                 if r.outcome in (Outcome.LANDED, Outcome.DUPLICATE))
        return ok / len(attempted)

    def summary(self) -> str:
        lines = [
            f"入库 {self.landed} · 重复 {self.count(Outcome.DUPLICATE)} · "
            f"拒收 {self.count(Outcome.REJECTED)} · "
            f"抽取失败 {self.count(Outcome.EXTRACT_FAILED)} · "
            f"抓取失败 {self.count(Outcome.FETCH_FAILED)} · "
            f"robots 拒绝 {self.count(Outcome.ROBOTS_DENIED)} · "
            f"配额耗尽 {self.count(Outcome.QUOTA_EXHAUSTED)}",
            f"抽取成功率 {self.extraction_success_rate * 100:.0f}%",
        ]
        return "\n".join(lines)


def load_sources(path: Path | None = None) -> dict:
    return yaml.safe_load((path or SOURCES_PATH).read_text(encoding="utf-8"))


class CrawlPipeline:
    def __init__(
        self,
        llm,
        data_dir: Path,
        fetcher: Fetcher | None = None,
        limiter: RateLimiter | None = None,
        known_rule_ids: set[str] | None = None,
        min_success_rate: float = 0.5,
    ):
        cfg = load_sources().get("meta") or {}
        self.limiter = limiter or RateLimiter(
            cases_per_hour=int(cfg.get("cases_per_hour", 50)),
            min_request_interval=float(cfg.get("default_request_interval", 3.0)),
        )
        self.fetcher = fetcher or Fetcher(gate=RobotsGate(), limiter=self.limiter)
        self.extractor = Extractor(llm)
        self.data_dir = Path(data_dir)
        self.known_rule_ids = known_rule_ids
        self.min_success_rate = min_success_rate
        self.dedup = DedupIndex()

    # ── 载入既有案例，避免重复抓 ──────────────────────────────

    def load_existing(self) -> int:
        n = 0
        for sub in ("structured", "structured_candidates"):
            d = self.data_dir / sub
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.json")):
                try:
                    self.dedup.add_existing(json.loads(p.read_text(encoding="utf-8")))
                    n += 1
                except Exception as exc:
                    logger.warning("载入 %s 失败：%s", p.name, exc)
        logger.info("已载入 %d 条既有案例用于去重", n)
        return n

    # ── 单条 ──────────────────────────────────────────────────

    def process(self, url: str, case_id: str, source_name: str = "") -> list[ItemResult]:
        """处理一个页面，返回该页面产出的**每个案例**的结果。

        ⚠️ 一个页面可能含多个案例。市监总局的典型案例通报是
        「一篇文章 = 七起案例」，按「一个 URL 一个案例」处理会把七个案子
        揉成一条，抽出来的金额和当事人全是错位的 —— 而且不会报错。

        配额按**案例**扣，不按页面扣：人工复核的负担是按案例算的。
        """
        if self.limiter.remaining_quota() <= 0:
            return [ItemResult(url, Outcome.QUOTA_EXHAUSTED,
                               issues=[f"本小时 {self.limiter.cases_per_hour} 条配额已用尽"])]

        try:
            fetched = self.fetcher.fetch(url)
        except RobotsDenied as exc:
            return [ItemResult(url, Outcome.ROBOTS_DENIED, issues=[str(exc)])]
        except Exception as exc:
            return [ItemResult(url, Outcome.FETCH_FAILED, issues=[str(exc)])]

        if not fetched.ok or not fetched.text.strip():
            return [ItemResult(url, Outcome.FETCH_FAILED,
                               issues=[f"HTTP {fetched.status} 或正文为空"])]

        # 原文整页存证一次：拆分是我们的加工，存证要存对方给的原样
        paths = Fetcher.persist(fetched, case_id, self.data_dir)

        segments = split_cases(fetched.text)
        out: list[ItemResult] = []

        for seg in segments:
            sid = f"{case_id}{seg.suffix}" if len(segments) > 1 else case_id

            if not self.limiter.try_consume_case():
                out.append(ItemResult(url, Outcome.QUOTA_EXHAUSTED, sid,
                                      [f"配额用尽，本页剩余 {len(segments) - len(out)} 个案例未处理"]))
                break

            out.append(self._process_segment(
                url, sid, seg, fetched, paths, source_name))

        return out

    def _process_segment(self, url, sid, seg, fetched, paths, source_name) -> ItemResult:
        try:
            extracted = self.extractor.extract(seg.text)
        except Exception as exc:
            return ItemResult(url, Outcome.EXTRACT_FAILED, sid, [str(exc)])

        case = to_case(extracted, sid, url, paths["raw_text_path"], source_name)
        case["raw_html_path"] = paths["raw_html_path"]
        case["fetched_at"] = fetched.fetched_at
        case["content_sha256"] = fetched.sha256
        if seg.title:
            if not case.get("title"):
                case["title"] = seg.title
            # 记下是原文的哪一节，回溯时能定位
            case["segment_index"] = seg.index
            case["segment_title"] = seg.title

        # 混编通报（如「铁拳行动典型案例」）一篇里既有违法广告也有电子秤作弊，
        # 标题级过滤挡不住。逐段标注相关性，**不删** —— 那些案例是真实可溯源的，
        # 只是对广告合规没用；不标注则等于把筛选成本转嫁给复核的人。
        tag_case(case, seg.text)

        # 校验只拿本节原文核对 —— 拿整页核会让 A 案的金额在 B 案的原文里"找得到"
        result = validate_case(case, seg.text, self.known_rule_ids)
        if result.rejected:
            return ItemResult(url, Outcome.REJECTED, sid,
                              [str(i) for i in result.issues], extracted.dropped)

        is_dup, existing, basis = self.dedup.check(result.case, seg.text)
        if is_dup:
            self.dedup.merge_source(existing, result.case)
            self._save(existing, existing.get("case_id") or sid)
            return ItemResult(url, Outcome.DUPLICATE, sid,
                              [f"与 {existing.get('case_id')} 重复（指纹口径：{basis}）"])

        self._save(result.case, sid)
        return ItemResult(url, Outcome.LANDED, sid,
                          [str(i) for i in result.issues], extracted.dropped)

    def _save(self, case: dict, case_id: str) -> Path:
        """写入候选库。**不写 structured** —— 两级入库的意义就在于人必须在环。"""
        out = self.data_dir / "structured_candidates"
        out.mkdir(parents=True, exist_ok=True)
        p = out / f"{case_id}.json"
        p.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        return p

    # ── 批量 ──────────────────────────────────────────────────

    def run(self, urls: list[tuple[str, str]], source_name: str = "") -> RunReport:
        """urls 为 [(url, case_id), ...]。"""
        report = RunReport(started_at=datetime.now(timezone.utc).isoformat())

        for url, case_id in urls:
            batch = self.process(url, case_id, source_name)
            report.results.extend(batch)
            for r in batch:
                logger.info("%s", r)

            if any(r.outcome == Outcome.QUOTA_EXHAUSTED for r in batch):
                logger.warning("配额耗尽，本轮收工。剩余 %d 条未处理。",
                               len(urls) - len(report.results))
                break

            # 熔断：抽取成功率掉下去多半是站点改版，继续跑只会产出垃圾候选
            if len(report.results) >= 5 and report.extraction_success_rate < self.min_success_rate:
                logger.error(
                    "抽取成功率 %.0f%% 低于阈值 %.0f%%，停止本轮。"
                    "多半是站点改版导致解析失效 —— 继续跑只会把人工复核的时间浪费在垃圾数据上。",
                    report.extraction_success_rate * 100, self.min_success_rate * 100,
                )
                break

        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report
