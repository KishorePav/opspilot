from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from opspilot.domain.models import EvidenceChunk

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25Index:
    def __init__(
        self,
        chunks: Sequence[EvidenceChunk],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self._chunks = list(chunks)
        self._k1 = k1
        self._b = b
        self._tokens = [tokenize(f"{chunk.title} {chunk.content}") for chunk in chunks]
        self._frequencies = [Counter(tokens) for tokens in self._tokens]
        self._average_length = (
            sum(len(tokens) for tokens in self._tokens) / len(self._tokens)
            if self._tokens
            else 0.0
        )
        self._document_frequency: Counter[str] = Counter()
        for tokens in self._tokens:
            self._document_frequency.update(set(tokens))

    def rank(self, query: str) -> list[tuple[EvidenceChunk, float]]:
        query_terms = tokenize(query)
        scored = [
            (chunk, self._score(index, query_terms))
            for index, chunk in enumerate(self._chunks)
        ]
        positive = [(chunk, score) for chunk, score in scored if score > 0]
        return sorted(positive, key=lambda item: (-item[1], item[0].chunk_id))

    def _score(self, index: int, query_terms: Sequence[str]) -> float:
        if not self._chunks or not self._average_length:
            return 0.0
        frequencies = self._frequencies[index]
        document_length = len(self._tokens[index])
        score = 0.0
        for term in query_terms:
            term_frequency = frequencies[term]
            if not term_frequency:
                continue
            documents_with_term = self._document_frequency[term]
            inverse_document_frequency = math.log(
                1 + (len(self._chunks) - documents_with_term + 0.5) / (documents_with_term + 0.5)
            )
            denominator = term_frequency + self._k1 * (
                1 - self._b + self._b * document_length / self._average_length
            )
            score += inverse_document_frequency * (
                term_frequency * (self._k1 + 1) / denominator
            )
        return score
