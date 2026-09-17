"""抓取与存证。

每次抓取都留下三样东西：原始 HTML、抽出的正文、内容的 sha256。

sha256 不是为了去重（去重用文号），是为了**存证**：
站点日后改版或删文时，能证明「我们当时看到的就是这个」。
一条引用了已删除页面的案例，没有存证就无从自证。
"""

from __future__ import annotations

import hashlib
import time
import html as html_lib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.crawler.policy import UA, RateLimiter, RobotsGate, build_ssl_context

logger = logging.getLogger(__name__)

_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANK = re.compile(r"\n{3,}")


def html_to_text(raw_html: str) -> str:
    """粗提正文。

    ⚠️ 这是**简易实现**：去脚本样式、标签换行、解实体、压空行。
    政府公示页结构简单，通常够用；遇到复杂模板会带进导航和页脚。
    正文质量直接影响抽取，真正铺开时应针对每个源写专用解析器 ——
    通用提取器在这个场景里是过渡方案，不是终局。
    """
    t = _SCRIPT.sub(" ", raw_html or "")
    t = re.sub(r"<(br|/p|/div|/tr|/li|/h[1-6])[^>]*>", "\n", t, flags=re.I)
    t = _TAG.sub("", t)
    t = html_lib.unescape(t)
    t = "\n".join(line.strip() for line in t.splitlines())
    return _BLANK.sub("\n\n", t).strip()


def _is_transient(exc: BaseException) -> bool:
    """判断异常是否值得重试。

    只重试传输层的抖动（连接重置、握手 EOF、超时）。HTTP 状态码不在此列 ——
    404 重试一百次还是 404，只是白白打扰对方。
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, httpx.TransportError)


@dataclass
class FetchResult:
    url: str
    status: int
    raw_html: str
    text: str
    sha256: str
    fetched_at: str
    ua: str = UA

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class Fetcher:
    """带 robots 门禁与限速的抓取器。

    顺序是刻意的：**先查 robots，再限速，最后才发请求**。
    反过来（先请求再查）等于已经打扰了对方才去问准不准。
    """

    def __init__(self, gate: RobotsGate | None = None,
                 limiter: RateLimiter | None = None,
                 client=None, timeout: float = 20.0, retries: int = 2,
                 allowed_hosts: set[str] | None = None):
        self.gate = gate or RobotsGate()
        self.limiter = limiter or RateLimiter()
        self.client = client
        self.timeout = timeout
        self.retries = retries
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or set())}
        self._http = None

    def _session(self):
        """复用连接。这既是效率，也是礼貌 —— 每次新建 TLS 握手对方更累。"""
        if self._http is None:
            import httpx

            self._http = httpx.Client(
                headers={"User-Agent": UA},
                timeout=self.timeout,
                follow_redirects=True,
                verify=build_ssl_context(),
            )
        return self._http

    def _request(self, url: str, method: str = "GET",
                 json_payload=None) -> tuple[int, str]:
        if self.client is not None and method == "GET":
            return self.client(url)
        r = self._session().request(method, url, json=json_payload)
        return r.status_code, r.text

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    def fetch(self, url: str, interval: float | None = None,
              method: str = "GET", json_payload=None) -> FetchResult:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"抓取地址必须使用 HTTPS：{url}")
        host = (parsed.hostname or "").lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise ValueError(f"抓取地址不在允许的官方域名中：{host or url}")
        self.gate.check(url)  # 不允许则抛 RobotsDenied，调用方必须处理

        delay = self.gate.crawl_delay(url, interval or self.limiter.min_request_interval)

        # 重试放在限速**里面**：每次重试都重新过一遍请求间隔。
        # 反过来（先重试再限速）等于对着一个正在抖动的站点连发几次请求。
        for attempt in range(self.retries + 1):
            waited = self.limiter.before_request(host, delay)
            if waited:
                logger.debug("为 %s 等待 %.1fs 以满足请求间隔", host, waited)
            try:
                status, body = self._request(url, method, json_payload)
            except Exception as exc:
                if attempt == self.retries or not _is_transient(exc):
                    raise
                logger.warning("%s 第 %d 次请求失败（%s），重试", url, attempt + 1, exc)
                continue
            if status == 429 and attempt < self.retries:
                logger.warning("%s 返回 429（限流），按目标要求等待 5 秒后重试（%d/%d）",
                               url, attempt + 1, self.retries)
                time.sleep(5)
                continue
            break

        return FetchResult(
            url=url,
            status=status,
            raw_html=body,
            text=html_to_text(body),
            sha256=hashlib.sha256((body or "").encode("utf-8")).hexdigest(),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def persist(result: FetchResult, case_id: str, data_dir: Path) -> dict[str, str]:
        """落盘原始 HTML 与正文，返回相对路径。

        ⚠️ **只写不删**（AGENTS.md 红线）。同名文件已存在时不覆盖，
        改写成带序号的新文件 —— 原始数据一旦被覆盖就找不回来了。
        """
        data_dir = Path(data_dir)
        html_dir = data_dir / "raw_html"
        text_dir = data_dir / "raw_text"
        html_dir.mkdir(parents=True, exist_ok=True)
        text_dir.mkdir(parents=True, exist_ok=True)

        def _unique(p: Path) -> Path:
            if not p.exists():
                return p
            i = 2
            while (alt := p.with_name(f"{p.stem}_{i}{p.suffix}")).exists():
                i += 1
            logger.warning("%s 已存在，改写入 %s（原始数据只增不覆盖）", p.name, alt.name)
            return alt

        hp = _unique(html_dir / f"{case_id}.html")
        hp.write_text(result.raw_html, encoding="utf-8")

        import json

        tp = _unique(text_dir / f"{case_id}.json")
        tp.write_text(json.dumps({
            "case_id": case_id,
            "source_url": result.url,
            "fetched_at": result.fetched_at,
            "user_agent": result.ua,
            "sha256": result.sha256,
            "text": result.text,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "raw_html_path": str(hp.relative_to(data_dir.parent)).replace("\\", "/"),
            "raw_text_path": str(tp.relative_to(data_dir.parent)).replace("\\", "/"),
        }
