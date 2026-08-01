from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Document:
    document_id: str
    title: str
    content: str
    source: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise ValueError("document_id must not be empty")
        if not self.content.strip():
            raise ValueError("content must not be empty")


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    chunk_id: str
    document_id: str
    title: str
    source: str
    ordinal: int
    content: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk: EvidenceChunk
    score: float
    lexical_rank: int | None
    vector_rank: int | None
