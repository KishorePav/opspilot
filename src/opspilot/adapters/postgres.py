from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from psycopg import Connection
from psycopg import Error as PsycopgError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from opspilot.domain.models import Document, EvidenceChunk, SearchHit
from opspilot.retrieval.base import RetrievalUnavailableError
from opspilot.retrieval.chunking import WordChunker
from opspilot.retrieval.embedding import EmbeddingProvider

_SCHEMA_EMBEDDING_DIMENSIONS = 1536

_INSERT_CHUNK_SQL = """
INSERT INTO evidence_chunks (
    chunk_id, document_id, source, title, ordinal, content, metadata, embedding
) VALUES (
    %(chunk_id)s,
    %(document_id)s,
    %(source)s,
    %(title)s,
    %(ordinal)s,
    %(content)s,
    %(metadata)s::jsonb,
    %(embedding)s::vector
)
"""

_SEARCH_SQL = """
WITH lexical AS (
    SELECT
        chunk_id,
        row_number() OVER (
            ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', %(query)s)) DESC,
                     chunk_id
        ) AS rank
    FROM evidence_chunks
    WHERE search_vector @@ websearch_to_tsquery('english', %(query)s)
      AND metadata @> %(filters)s::jsonb
    ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', %(query)s)) DESC,
             chunk_id
    LIMIT %(candidate_limit)s
),
semantic AS (
    SELECT
        chunk_id,
        row_number() OVER (
            ORDER BY embedding <=> %(query_embedding)s::vector, chunk_id
        ) AS rank
    FROM evidence_chunks
    WHERE metadata @> %(filters)s::jsonb
    ORDER BY embedding <=> %(query_embedding)s::vector, chunk_id
    LIMIT %(candidate_limit)s
),
candidates AS (
    SELECT chunk_id FROM lexical
    UNION
    SELECT chunk_id FROM semantic
)
SELECT
    evidence.chunk_id,
    evidence.document_id,
    evidence.source,
    evidence.title,
    evidence.ordinal,
    evidence.content,
    evidence.metadata,
    lexical.rank AS lexical_rank,
    semantic.rank AS vector_rank,
    coalesce(%(lexical_weight)s / (%(rank_constant)s + lexical.rank), 0.0) +
    coalesce(%(vector_weight)s / (%(rank_constant)s + semantic.rank), 0.0) AS score
FROM candidates
JOIN evidence_chunks AS evidence USING (chunk_id)
LEFT JOIN lexical USING (chunk_id)
LEFT JOIN semantic USING (chunk_id)
ORDER BY score DESC, evidence.chunk_id
LIMIT %(top_k)s
"""


def _serialize_vector(vector: Sequence[float]) -> str:
    return "[" + ",".join(format(value, ".17g") for value in vector) + "]"


class PostgresHybridRetriever:
    """Persistence-backed lexical/vector retrieval with database-side rank fusion."""

    def __init__(
        self,
        database_url: str,
        embedder: EmbeddingProvider,
        *,
        chunker: WordChunker | None = None,
        pool_min_size: int = 1,
        pool_max_size: int = 8,
        lexical_weight: float = 1.0,
        vector_weight: float = 1.0,
        rank_constant: int = 60,
    ) -> None:
        if embedder.dimensions != _SCHEMA_EMBEDDING_DIMENSIONS:
            raise ValueError(
                "PostgreSQL retrieval requires "
                f"{_SCHEMA_EMBEDDING_DIMENSIONS}-dimension embeddings"
            )
        if lexical_weight < 0 or vector_weight < 0:
            raise ValueError("fusion weights must not be negative")
        if rank_constant < 1:
            raise ValueError("rank constant must be positive")

        self._embedder = embedder
        self._chunker = chunker or WordChunker()
        self._lexical_weight = lexical_weight
        self._vector_weight = vector_weight
        self._rank_constant = rank_constant
        self._pool = cast(
            ConnectionPool[Connection[dict[str, Any]]],
            ConnectionPool(
                conninfo=database_url,
                min_size=pool_min_size,
                max_size=pool_max_size,
                kwargs={"row_factory": dict_row},
                open=False,
            ),
        )
        try:
            self._pool.open(wait=True)
        except (PsycopgError, PoolTimeout) as exc:
            raise RetrievalUnavailableError("retrieval database is unavailable") from exc

    def __enter__(self) -> PostgresHybridRetriever:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._pool.close()

    def index_documents(self, documents: Sequence[Document]) -> int:
        chunks = [chunk for document in documents for chunk in self._chunker.chunk(document)]
        if not chunks:
            return 0

        vectors = self._embedder.embed(
            [f"{chunk.title}\n{chunk.content}" for chunk in chunks]
        )
        if len(chunks) != len(vectors):
            raise RuntimeError("embedding provider returned an unexpected vector count")
        if any(len(vector) != _SCHEMA_EMBEDDING_DIMENSIONS for vector in vectors):
            raise RuntimeError("embedding provider returned an unexpected vector dimension")

        document_ids = sorted({document.document_id for document in documents})
        records = [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "source": chunk.source,
                "title": chunk.title,
                "ordinal": chunk.ordinal,
                "content": chunk.content,
                "metadata": json.dumps(dict(chunk.metadata), sort_keys=True),
                "embedding": _serialize_vector(vector),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

        try:
            with self._pool.connection() as connection, connection.transaction():
                connection.execute(
                    "DELETE FROM evidence_chunks WHERE document_id = ANY(%s)",
                    (document_ids,),
                )
                with connection.cursor() as cursor:
                    cursor.executemany(_INSERT_CHUNK_SQL, records)
        except (PsycopgError, PoolTimeout) as exc:
            raise RetrievalUnavailableError("evidence ingestion failed") from exc
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

        query_vectors = self._embedder.embed([query])
        if len(query_vectors) != 1:
            raise RuntimeError("embedding provider returned an unexpected vector count")
        query_vector = query_vectors[0]
        if len(query_vector) != _SCHEMA_EMBEDDING_DIMENSIONS:
            raise RuntimeError("embedding provider returned an unexpected vector dimension")

        parameters = {
            "query": query,
            "query_embedding": _serialize_vector(query_vector),
            "filters": json.dumps(dict(filters or {}), sort_keys=True),
            "candidate_limit": min(max(top_k * 8, 40), 400),
            "top_k": top_k,
            "lexical_weight": self._lexical_weight,
            "vector_weight": self._vector_weight,
            "rank_constant": self._rank_constant,
        }
        try:
            with self._pool.connection() as connection:
                rows = connection.execute(_SEARCH_SQL, parameters).fetchall()
        except (PsycopgError, PoolTimeout) as exc:
            raise RetrievalUnavailableError("retrieval database is unavailable") from exc

        return [self._to_search_hit(row) for row in rows]

    @staticmethod
    def _to_search_hit(row: Mapping[str, Any]) -> SearchHit:
        raw_metadata = row["metadata"]
        if not isinstance(raw_metadata, dict):
            raise RuntimeError("database returned invalid evidence metadata")
        metadata = {str(key): str(value) for key, value in raw_metadata.items()}
        return SearchHit(
            chunk=EvidenceChunk(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                source=str(row["source"]),
                title=str(row["title"]),
                ordinal=int(row["ordinal"]),
                content=str(row["content"]),
                metadata=metadata,
            ),
            score=float(row["score"]),
            lexical_rank=int(row["lexical_rank"]) if row["lexical_rank"] is not None else None,
            vector_rank=int(row["vector_rank"]) if row["vector_rank"] is not None else None,
        )
