from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from opspilot.domain.models import EvidenceChunk, SearchHit


def reciprocal_rank_fusion(
    lexical: Sequence[tuple[EvidenceChunk, float]],
    vector: Sequence[tuple[EvidenceChunk, float]],
    *,
    lexical_weight: float = 1.0,
    vector_weight: float = 1.0,
    rank_constant: int = 60,
) -> list[SearchHit]:
    if lexical_weight < 0 or vector_weight < 0:
        raise ValueError("fusion weights must not be negative")
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")

    chunks: dict[str, EvidenceChunk] = {}
    lexical_ranks: dict[str, int] = {}
    vector_ranks: dict[str, int] = {}
    scores: defaultdict[str, float] = defaultdict(float)

    for rank, (chunk, _) in enumerate(lexical, start=1):
        chunks[chunk.chunk_id] = chunk
        lexical_ranks[chunk.chunk_id] = rank
        scores[chunk.chunk_id] += lexical_weight / (rank_constant + rank)

    for rank, (chunk, _) in enumerate(vector, start=1):
        chunks[chunk.chunk_id] = chunk
        vector_ranks[chunk.chunk_id] = rank
        scores[chunk.chunk_id] += vector_weight / (rank_constant + rank)

    hits = [
        SearchHit(
            chunk=chunk,
            score=scores[chunk_id],
            lexical_rank=lexical_ranks.get(chunk_id),
            vector_rank=vector_ranks.get(chunk_id),
        )
        for chunk_id, chunk in chunks.items()
    ]
    return sorted(hits, key=lambda hit: (-hit.score, hit.chunk.chunk_id))
