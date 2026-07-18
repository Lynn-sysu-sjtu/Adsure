# -*- coding: utf-8 -*-
"""Precomputed vector index for rule recall.vector_text."""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


PROJECT_BASE = Path(__file__).resolve().parents[1]
DEFAULT_VECTOR_INDEX_PATH = PROJECT_BASE / "vectorbase" / "rule_vector_index.json"


def vector_text_hash(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _semantic_rule_records(rules):
    records = []
    for rule in rules:
        recall = rule.get("recall", {}) or {}
        trigger_layer = recall.get("trigger_layer") or "content"
        semantic_role = recall.get("semantic_role") or "fallback"
        if trigger_layer != "content":
            continue
        if not recall.get("semantic_enabled"):
            continue
        if semantic_role == "disabled":
            continue
        vector_text = recall.get("vector_text") or ""
        if not vector_text:
            continue
        records.append(
            {
                "rule_id": rule.get("rule_id"),
                "serial_no": rule.get("serial_no"),
                "title": rule.get("title"),
                "vector_text": vector_text,
                "vector_text_hash": vector_text_hash(vector_text),
                "source_file": rule.get("_source_file"),
            }
        )
    return [record for record in records if record.get("rule_id")]


def _chunks(items, size):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def build_rule_vector_index(
    rules,
    output_path=DEFAULT_VECTOR_INDEX_PATH,
    embedding_client=None,
    model=None,
    batch_size=32,
):
    if embedding_client is None:
        from zhipu_embedding_client import ZhipuEmbeddingClient

        embedding_client = ZhipuEmbeddingClient(model=model)
        model = embedding_client.model
    model = model or getattr(embedding_client, "model", None) or "unknown"

    records = _semantic_rule_records(rules)
    vectors = []
    for batch in _chunks(records, batch_size):
        embeddings = embedding_client.embed_texts([item["vector_text"] for item in batch])
        for item, embedding in zip(batch, embeddings):
            vectors.append({**item, "embedding": embedding})

    payload = {
        "meta": {
            "index_type": "rule_vector_text_embedding",
            "backend": "zhipu",
            "model": model,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "vector_count": len(vectors),
        },
        "vectors": vectors,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_rule_vector_index(path=DEFAULT_VECTOR_INDEX_PATH):
    path = Path(path)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = {}
    for item in payload.get("vectors", []):
        rule_id = item.get("rule_id")
        text_hash = item.get("vector_text_hash")
        embedding = item.get("embedding")
        if rule_id and text_hash and embedding:
            entries[(rule_id, text_hash)] = item
    return entries


def main():
    parser = argparse.ArgumentParser(description="Build cached embeddings for rule recall.vector_text.")
    parser.add_argument("--base-dir", default=str(PROJECT_BASE), help="Project base dir containing jsonbase.")
    parser.add_argument("--output", default=str(DEFAULT_VECTOR_INDEX_PATH), help="Output vector index JSON path.")
    parser.add_argument("--model", default=None, help="Embedding model, defaults to ZHIPU_EMBEDDING_MODEL.")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    from kg_rule_store import load_rule_library

    library = load_rule_library(Path(args.base_dir))
    rules = library["data"].get("rules", [])
    index = build_rule_vector_index(
        rules,
        output_path=Path(args.output),
        model=args.model,
        batch_size=args.batch_size,
    )
    print(f"wrote {index['meta']['vector_count']} vectors to {args.output}")


if __name__ == "__main__":
    main()

