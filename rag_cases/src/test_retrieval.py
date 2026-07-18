import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path


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


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
    bigrams = [words[i] + words[i + 1] for i in range(len(words) - 1)]
    return words + bigrams


def bm25_scores(query: str, chunks: list[dict]) -> list[tuple[float, dict]]:
    tokenized_docs = [tokenize(chunk.get("text", "")) for chunk in chunks]
    doc_lengths = [len(tokens) for tokens in tokenized_docs]
    avgdl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 0
    df: Counter[str] = Counter()
    for tokens in tokenized_docs:
        df.update(set(tokens))

    query_terms = tokenize(query)
    scores = []
    k1 = 1.5
    b = 0.75
    total_docs = len(chunks)
    for chunk, tokens, doc_len in zip(chunks, tokenized_docs, doc_lengths):
        tf = Counter(tokens)
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (total_docs - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1 - b + b * doc_len / (avgdl or 1))
            score += idf * tf[term] * (k1 + 1) / denom
        scores.append((score, chunk))
    return sorted(scores, key=lambda item: item[0], reverse=True)


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
