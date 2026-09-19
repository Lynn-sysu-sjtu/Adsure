import argparse
import json
from pathlib import Path

from src.retrieval import bm25_scores, tokenize


DEFAULT_CHUNKS_PATH = Path("__auto__")
DEFAULT_QUERY = "普通食品宣传降血糖"

SECTOR_QUERY_TERMS = [
    "游戏",
    "抽奖",
    "概率",
    "福利码",
    "美妆",
    "化妆品",
    "杀菌",
    "消炎",
    "医疗用语",
    "保健品",
    "普通食品",
    "会销",
    "包装",
    "抑制肿瘤",
    "心脑血管",
]


def search(
    query: str,
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    top_k: int = 5,
) -> list[dict]:
    if chunks_path == DEFAULT_CHUNKS_PATH:
        sector_path = Path("data/chunks/sector_candidate_chunks.json")
        if sector_path.exists() and any(term in query for term in SECTOR_QUERY_TERMS):
            chunks_path = sector_path
        else:
            for fallback in [
                Path("data/chunks/candidate_chunks.json"),
                Path("data/chunks/production_chunks.json"),
                Path("data/chunks/test_chunks.json"),
                Path("data/chunks/chunks.json"),
                Path("data/chunks_samples/chunks.json"),
            ]:
                if fallback.exists():
                    chunks_path = fallback
                    break
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
    results = []
    for score, chunk in bm25_scores(query, chunks)[:top_k]:
        result = dict(chunk)
        result["score"] = round(score, 6)
        results.append(result)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local BM25 retrieval against chunks.")
    parser.add_argument("--chunks-path", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    print(json.dumps(search(args.query, args.chunks_path, args.top_k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
