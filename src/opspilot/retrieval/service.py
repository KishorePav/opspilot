from __future__ import annotations

from collections.abc import Mapping, Sequence

from opspilot.domain.models import Document, EvidenceChunk, SearchHit
from opspilot.retrieval.bm25 import BM25Index
from opspilot.retrieval.chunking import WordChunker
from opspilot.retrieval.embedding import EmbeddingProvider, cosine_similarity
from opspilot.retrieval.fusion import reciprocal_rank_fusion


class HybridRetriever:
    def __init__(
        self,
        embedder: EmbeddingProvider,
        *,
        chunker: WordChunker | None = None,
        lexical_weight: float = 1.0,
        vector_weight: float = 1.0,
    ) -> None:
        self._embedder = embedder
        self._chunker = chunker or WordChunker()
        self._lexical_weight = lexical_weight
        self._vector_weight = vector_weight
        self._chunks: list[EvidenceChunk] = []
        self._vectors: dict[str, list[float]] = {}

    def index_documents(self, documents: Sequence[Document]) -> int:
        chunks = [chunk for document in documents for chunk in self._chunker.chunk(document)]
        vectors = self._embedder.embed(
            [f"{chunk.title}\n{chunk.content}" for chunk in chunks]
        )
        if len(chunks) != len(vectors):
            raise RuntimeError("embedding provider returned an unexpected vector count")
        self._chunks = chunks
        self._vectors = {
            chunk.chunk_id: vector for chunk, vector in zip(chunks, vectors, strict=True)
        }
        return len(chunks)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: Mapping[str, str] | None = None,
    ) -> list[SearchHit]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1 or top_k > 50:
            raise ValueError("top_k must be between 1 and 50")

        candidates = [chunk for chunk in self._chunks if self._matches(chunk, filters)]
        if not candidates:
            return []

        lexical = BM25Index(candidates).rank(query)
        query_vector = self._embedder.embed([query])[0]
        vector = sorted(
            (
                (chunk, cosine_similarity(query_vector, self._vectors[chunk.chunk_id]))
                for chunk in candidates
            ),
            key=lambda item: (-item[1], item[0].chunk_id),
        )
        fused = reciprocal_rank_fusion(
            lexical,
            vector,
            lexical_weight=self._lexical_weight,
            vector_weight=self._vector_weight,
        )
        return fused[:top_k]

    @staticmethod
    def _matches(chunk: EvidenceChunk, filters: Mapping[str, str] | None) -> bool:
        if not filters:
            return True
        return all(chunk.metadata.get(key) == value for key, value in filters.items())
