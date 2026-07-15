import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path


DEFAULT_RAW_HTML_DIR = Path("data/raw_html")
DEFAULT_RAW_TEXT_DIR = Path("data/raw_text")


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def html_to_text(html: str) -> str:
    parser = TextExtractor()
    parser.feed(html)
    return "\n".join(parser.parts)


def extract_title(html: str, text: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    if not match:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if match:
        return " ".join(html_to_text(match.group(1)).split())
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:80]


def convert_one(raw_html_path: Path, raw_text_dir: Path) -> Path | None:
    payload = json.loads(raw_html_path.read_text(encoding="utf-8"))
    case_id = payload["case_id"]
    raw_text_dir.mkdir(parents=True, exist_ok=True)
    output_path = raw_text_dir / f"{case_id}.json"
    if output_path.exists():
        return None

    text = html_to_text(payload.get("html", ""))
    output = {
        "case_id": case_id,
        "title": extract_title(payload.get("html", ""), text),
        "source_id": payload.get("source_id", ""),
        "source_type": payload.get("source_type", ""),
        "source_name": payload.get("source_name", ""),
        "source_url": payload.get("source_url", ""),
        "priority": payload.get("priority", ""),
        "raw_html_path": str(raw_html_path),
        "raw_text_path": str(output_path),
        "case_text": text,
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def run(
    raw_html_dir: Path = DEFAULT_RAW_HTML_DIR,
    raw_text_dir: Path = DEFAULT_RAW_TEXT_DIR,
) -> list[Path]:
    outputs = []
    for raw_html_path in sorted(raw_html_dir.glob("*.json")):
        path = convert_one(raw_html_path, raw_text_dir)
        if path:
            outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract readable text from raw HTML JSON files.")
    parser.add_argument("--raw-html-dir", type=Path, default=DEFAULT_RAW_HTML_DIR)
    parser.add_argument("--raw-text-dir", type=Path, default=DEFAULT_RAW_TEXT_DIR)
    args = parser.parse_args()

    outputs = run(args.raw_html_dir, args.raw_text_dir)
    for path in outputs:
        print(path)
    if not outputs:
        print("No new raw_text files written.")


if __name__ == "__main__":
    main()
