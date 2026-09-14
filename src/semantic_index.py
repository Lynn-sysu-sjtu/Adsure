from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DEFAULT_MODEL_NAME = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_CHUNKS_PATH = Path("data/chunks/production_chunks.json")
DEFAULT_INDEX_PATH = Path("data/chunks/production_semantic_index.json")


def chunks_fingerprint(chunks: list[dict]) -> str:
    payload = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "text": semantic_text(chunk),
        }
        for chunk in chunks
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def semantic_text(chunk: dict) -> str:
    fields = chunk.get("search_fields") or {}
    parts = [
        fields.get("vector_text"),
        fields.get("illegal_claims"),
        fields.get("risk_dimensions"),
        fields.get("product_or_service"),
        fields.get("regulatory_logic"),
    ]
    normalized = []
    for value in parts:
        if isinstance(value, list):
            normalized.extend(str(item) for item in value if item)
        elif value:
            normalized.append(str(value))
    return "。".join(normalized) or str(chunk.get("text", ""))


def load_sentence_transformer(
    model_name: str,
    *,
    local_files_only: bool,
):
    # The text-only encoder does not need torchvision. Some macOS Python
    # environments contain an incompatible torchvision build that otherwise
    # prevents transformers from importing. Disable that optional backend
    # before importing sentence-transformers.
    import transformers.utils.import_utils as transformers_imports

    transformers_imports._torchvision_available = False
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        model_name,
        local_files_only=local_files_only,
    )


def model_encoder(
    model_name: str,
    *,
    local_files_only: bool = True,
) -> Callable[[list[str]], list[list[float]]]:
    model = load_sentence_transformer(
        model_name,
        local_files_only=local_files_only,
    )

    def encode(texts: list[str]) -> list[list[float]]:
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    return encode


def build_index(
    chunks: list[dict],
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    encoder: Callable[[list[str]], list[list[float]]] | None = None,
    local_files_only: bool = True,
) -> dict:
    resolved_encoder = encoder or model_encoder(
        model_name,
        local_files_only=local_files_only,
    )
    texts = [semantic_text(chunk) for chunk in chunks]
    embeddings = resolved_encoder(texts) if texts else []
    if len(embeddings) != len(chunks):
        raise ValueError("语义编码结果数量与切片数量不一致")
    dimension = len(embeddings[0]) if embeddings else 0
    if any(len(vector) != dimension for vector in embeddings):
        raise ValueError("语义编码向量维度不一致")
    return {
        "index_type": "dense_sentence_embedding",
        "model_name": model_name,
        "dimension": dimension,
        "normalized": True,
        "chunk_fingerprint": chunks_fingerprint(chunks),
        "document_count": len(chunks),
        "documents": [
            {
                "chunk_id": chunk["chunk_id"],
                "case_id": chunk["case_id"],
                "embedding": [round(float(value), 8) for value in vector],
            }
            for chunk, vector in zip(chunks, embeddings)
        ],
    }


def run(
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    index_path: Path = DEFAULT_INDEX_PATH,
    *,
    model_name: str = DEFAULT_MODEL_NAME,
    local_files_only: bool = True,
) -> Path:
    chunks = (
        json.loads(chunks_path.read_text(encoding="utf-8"))
        if chunks_path.exists()
        else []
    )
    index = build_index(
        chunks,
        model_name=model_name,
        local_files_only=local_files_only,
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return index_path


@dataclass(frozen=True)
class SemanticScore:
    chunk_id: str
    score: float


class SemanticIndex:
    def __init__(
        self,
        payload: dict,
        *,
        encoder: Callable[[list[str]], list[list[float]]] | None = None,
        local_files_only: bool = True,
    ):
        if payload.get("index_type") != "dense_sentence_embedding":
            raise ValueError("语义索引类型不受支持")
        self.model_name = str(payload.get("model_name") or "")
        self.dimension = int(payload.get("dimension") or 0)
        self.chunk_fingerprint = str(payload.get("chunk_fingerprint") or "")
        documents = payload.get("documents", [])
        if not isinstance(documents, list):
            raise ValueError("语义索引 documents 必须是数组")
        document_ids = [str(document.get("chunk_id") or "") for document in documents]
        if not all(document_ids) or len(set(document_ids)) != len(document_ids):
            raise ValueError("语义索引 chunk_id 缺失或重复")
        declared_count = int(payload.get("document_count") or 0)
        if declared_count != len(documents):
            raise ValueError("语义索引文档数量与声明不一致")
        if documents and self.dimension <= 0:
            raise ValueError("语义索引向量维度无效")
        self.embeddings = {
            str(document["chunk_id"]): [float(value) for value in document["embedding"]]
            for document in documents
        }
        if any(len(vector) != self.dimension for vector in self.embeddings.values()):
            raise ValueError("语义索引向量维度不一致")
        self._encoder = encoder
        self.local_files_only = local_files_only
        self.load_error = ""

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        encoder: Callable[[list[str]], list[list[float]]] | None = None,
        local_files_only: bool = True,
    ) -> "SemanticIndex":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            payload,
            encoder=encoder,
            local_files_only=local_files_only,
        )

    def _resolved_encoder(self) -> Callable[[list[str]], list[list[float]]]:
        if self._encoder is None:
            self._encoder = model_encoder(
                self.model_name,
                local_files_only=self.local_files_only,
            )
        return self._encoder

    def scores(self, query: str, chunk_ids: set[str]) -> list[SemanticScore]:
        try:
            vectors = self._resolved_encoder()([query])
        except Exception as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"
            return []
        if len(vectors) != 1 or len(vectors[0]) != self.dimension:
            self.load_error = "语义查询向量维度不一致"
            return []
        query_vector = vectors[0]
        results = []
        for chunk_id in chunk_ids:
            vector = self.embeddings.get(chunk_id)
            if vector is None:
                continue
            score = sum(left * right for left, right in zip(query_vector, vector))
            results.append(SemanticScore(chunk_id=chunk_id, score=float(score)))
        return sorted(results, key=lambda item: item.score, reverse=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local dense semantic index for Adsure RAG."
    )
    parser.add_argument("--chunks-path", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument(
        "--model",
        default=os.getenv("CASE_ENGINE_EMBEDDING_MODEL", DEFAULT_MODEL_NAME),
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="Allow the model loader to access remote model files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = run(
        args.chunks_path,
        args.index_path,
        model_name=args.model,
        local_files_only=not args.allow_download,
    )
    print(path)


if __name__ == "__main__":
    main()
