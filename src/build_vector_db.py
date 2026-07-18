import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from .test_retrieval import tokenize
except ImportError:
    from test_retrieval import tokenize


DEFAULT_CHUNKS_PATH = Path("data/chunks/chunks.json")
DEFAULT_INDEX_PATH = Path("data/chunks/lexical_index.json")


def build_index(chunks: list[dict]) -> dict:
    documents = []
    document_frequency: Counter[str] = Counter()
    for chunk in chunks:
        tokens = tokenize(chunk.get("text", ""))
        token_counts = Counter(tokens)
        document_frequency.update(token_counts.keys())
        documents.append(
            {
                "chunk_id": chunk["chunk_id"],
                "case_id": chunk["case_id"],
                "token_counts": dict(token_counts),
                "length": sum(token_counts.values()),
            }
        )
    return {
        "index_type": "local_bm25_lexical",
        "document_count": len(documents),
        "document_frequency": dict(document_frequency),
        "documents": documents,
    }


def run(
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    index_path: Path = DEFAULT_INDEX_PATH,
) -> Path:
    chunks = json.loads(chunks_path.read_text(encoding="utf-8")) if chunks_path.exists() else []
    index = build_index(chunks)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local lexical retrieval index.")
    parser.add_argument("--chunks-path", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    args = parser.parse_args()
    print(run(args.chunks_path, args.index_path))


if __name__ == "__main__":
    main()
