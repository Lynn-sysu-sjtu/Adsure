import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import yaml


DEFAULT_SOURCES_PATH = Path("data/sources/sources.yaml")
DEFAULT_RAW_HTML_DIR = Path("data/raw_html")

FetchFn = Callable[[str], str]


@dataclass(frozen=True)
class Source:
    source_id: str
    source_name: str
    source_type: str
    priority: str
    base_url: str
    list_urls: tuple[str, ...]
    detail_urls: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    crawl_mode: str
    notes: str = ""
    sample_file: str | None = None


OFFLINE_SAMPLE_PAGES = [
    {
        "source_id": "offline_sample",
        "source_name": "离线示例数据（非真实处罚事实来源）",
        "source_type": "offline_sample",
        "priority": "DEMO",
        "source_url": "sample://offline/absolute-terms",
        "html": """
        <html>
          <head><title>离线示例：绝对化广告用语</title></head>
          <body>
            <h1>离线示例：某互联网广告绝对化用语</h1>
            <p>某公司在互联网广告中宣称产品为“国家级最佳”。</p>
            <p>监管机关认为相关宣传构成绝对化用语违法，并处以罚款10000元。</p>
            <p>本数据仅用于离线演示，不是处罚事实来源。</p>
          </body>
        </html>
        """,
    }
]


def load_sources(path: Path = DEFAULT_SOURCES_PATH) -> list[Source]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = []
    for item in data.get("sources", []):
        list_urls = item.get("list_urls") or item.get("list_url") or []
        if isinstance(list_urls, str):
            list_urls = [list_urls]
        detail_urls = item.get("detail_urls") or []
        sources.append(
            Source(
                source_id=item["source_id"],
                source_name=item["source_name"],
                source_type=item["source_type"],
                priority=item["priority"],
                base_url=item["base_url"],
                list_urls=tuple(list_urls),
                detail_urls=tuple(detail_urls),
                allowed_domains=tuple(item.get("allowed_domains") or []),
                crawl_mode=item.get("crawl_mode", "manual_seed"),
                notes=item.get("notes", ""),
                sample_file=item.get("sample_file"),
            )
        )
    return sources


def case_id_for(source_id: str, url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{source_id}__{digest}"


def default_fetcher(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "ads-penalty-rag/0.1 (+manual-seed; respectful crawling)"
        },
    )
    with urlopen(req, timeout=20) as response:
        return response.read().decode(response.headers.get_content_charset() or "utf-8")


def is_placeholder(url: str) -> bool:
    return "手动填入" in url or not url.strip()


def is_allowed_url(url: str, source: Source) -> bool:
    parsed = urlparse(url)
    if parsed.scheme == "sample":
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    if not source.allowed_domains:
        return True
    hostname = parsed.hostname or ""
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in source.allowed_domains)


def extract_links(html: str, base_url: str) -> list[str]:
    hrefs = re.findall(r"""href=["']([^"']+)["']""", html, flags=re.I)
    links = []
    for href in hrefs:
        if href.startswith(("#", "javascript:", "mailto:")):
            continue
        links.append(urljoin(base_url, href))
    return links


def extract_sample_articles(sample_html: str) -> dict[str, str]:
    articles: dict[str, str] = {}
    pattern = re.compile(
        r"""<article\b(?P<attrs>[^>]*)>(?P<body>.*?)</article>""",
        flags=re.I | re.S,
    )
    url_pattern = re.compile(r"""data-source-url=["'](?P<url>[^"']+)["']""", flags=re.I)
    for match in pattern.finditer(sample_html):
        url_match = url_pattern.search(match.group("attrs"))
        if not url_match:
            continue
        url = url_match.group("url")
        articles[url] = f"<html><body><article{match.group('attrs')}>{match.group('body')}</article></body></html>"
    return articles


def load_sample_html(source: Source, url: str, base_dir: Path) -> str | None:
    if not source.sample_file:
        return None
    sample_path = Path(source.sample_file)
    if not sample_path.is_absolute():
        sample_path = base_dir / sample_path
    sample_html = sample_path.read_text(encoding="utf-8")
    return extract_sample_articles(sample_html).get(url)


def discover_detail_urls(source: Source, fetcher: FetchFn, allow_network: bool) -> list[str]:
    return list(source.detail_urls)


def save_raw_html(
    raw_html_dir: Path,
    *,
    case_id: str,
    source_id: str,
    source_name: str,
    source_type: str,
    priority: str,
    source_url: str,
    html: str,
) -> Path | None:
    raw_html_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_html_dir / f"{case_id}.json"
    if output_path.exists():
        return None
    payload = {
        "case_id": case_id,
        "source_id": source_id,
        "source_name": source_name,
        "source_type": source_type,
        "priority": priority,
        "source_url": source_url,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "html": html,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def write_offline_samples(raw_html_dir: Path) -> list[Path]:
    saved = []
    for sample in OFFLINE_SAMPLE_PAGES:
        case_id = case_id_for(sample["source_id"], sample["source_url"])
        path = save_raw_html(
            raw_html_dir,
            case_id=case_id,
            source_id=sample["source_id"],
            source_name=sample["source_name"],
            source_type=sample["source_type"],
            priority=sample["priority"],
            source_url=sample["source_url"],
            html=sample["html"],
        )
        if path:
            saved.append(path)
    return saved


def run(
    sources_path: Path = DEFAULT_SOURCES_PATH,
    raw_html_dir: Path = DEFAULT_RAW_HTML_DIR,
    fetcher: FetchFn = default_fetcher,
    allow_network: bool = False,
    base_dir: Path = Path("."),
) -> list[Path]:
    saved = []
    for source in load_sources(sources_path):
        detail_urls = discover_detail_urls(source, fetcher, allow_network)
        for url in detail_urls:
            if is_placeholder(url) or not is_allowed_url(url, source):
                continue
            html = load_sample_html(source, url, base_dir)
            if html is None:
                if not allow_network and urlparse(url).scheme in {"http", "https"}:
                    continue
                html = fetcher(url)
            case_id = case_id_for(source.source_id, url)
            path = save_raw_html(
                raw_html_dir,
                case_id=case_id,
                source_id=source.source_id,
                source_name=source.source_name,
                source_type=source.source_type,
                priority=source.priority,
                source_url=url,
                html=html,
            )
            if path:
                saved.append(path)
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch official penalty case HTML.")
    parser.add_argument("--sources-path", type=Path, default=DEFAULT_SOURCES_PATH)
    parser.add_argument("--raw-html-dir", type=Path, default=DEFAULT_RAW_HTML_DIR)
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--offline-sample", action="store_true")
    args = parser.parse_args()

    saved: list[Path] = []
    if args.offline_sample:
        saved.extend(write_offline_samples(args.raw_html_dir))
    saved.extend(
        run(
            sources_path=args.sources_path,
            raw_html_dir=args.raw_html_dir,
            allow_network=args.allow_network,
            base_dir=Path("."),
        )
    )
    for path in saved:
        print(path)
    if not saved:
        print("No new raw_html files written.")


if __name__ == "__main__":
    main()
