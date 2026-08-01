from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from opspilot.domain.models import Document, EvidenceChunk

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    max_words: int = 140
    overlap_words: int = 25

    def __post_init__(self) -> None:
        if self.max_words < 10:
            raise ValueError("max_words must be at least 10")
        if self.overlap_words < 0:
            raise ValueError("overlap_words must not be negative")
        if self.overlap_words >= self.max_words:
            raise ValueError("overlap_words must be smaller than max_words")


class WordChunker:
    def __init__(self, config: ChunkingConfig | None = None) -> None:
        self.config = config or ChunkingConfig()

    def chunk(self, document: Document) -> list[EvidenceChunk]:
        normalized = _WHITESPACE.sub(" ", document.content).strip()
        words = normalized.split(" ")
        step = self.config.max_words - self.config.overlap_words
        chunks: list[EvidenceChunk] = []

        for ordinal, start in enumerate(range(0, len(words), step)):
            text = " ".join(words[start : start + self.config.max_words]).strip()
            if not text:
                continue
            digest_input = f"{document.document_id}:{ordinal}:{text}".encode()
            chunk_id = hashlib.sha256(digest_input).hexdigest()[:24]
            chunks.append(
                EvidenceChunk(
                    chunk_id=chunk_id,
                    document_id=document.document_id,
                    title=document.title,
                    source=document.source,
                    ordinal=ordinal,
                    content=text,
                    metadata=dict(document.metadata),
                )
            )
            if start + self.config.max_words >= len(words):
                break

        return chunks
