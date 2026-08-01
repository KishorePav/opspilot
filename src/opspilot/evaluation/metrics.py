from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


def recall_at_k(expected: set[str], ranked: Sequence[str], k: int) -> float:
    if not expected:
        return 1.0
    return len(expected.intersection(ranked[:k])) / len(expected)


def reciprocal_rank(expected: set[str], ranked: Sequence[str]) -> float:
    for rank, identifier in enumerate(ranked, start=1):
        if identifier in expected:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(expected: set[str], ranked: Sequence[str], k: int) -> float:
    if not expected:
        return 1.0
    actual = sum(
        1.0 / math.log2(rank + 1)
        for rank, identifier in enumerate(ranked[:k], start=1)
        if identifier in expected
    )
    ideal_hits = min(len(expected), k)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return actual / ideal if ideal else 0.0


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    cases: int
    recall_at_k: float
    mean_reciprocal_rank: float
    ndcg_at_k: float


def summarize(
    cases: Iterable[tuple[set[str], Sequence[str]]],
    *,
    k: int,
) -> EvaluationSummary:
    materialized = list(cases)
    if not materialized:
        raise ValueError("at least one evaluation case is required")
    return EvaluationSummary(
        cases=len(materialized),
        recall_at_k=sum(recall_at_k(expected, ranked, k) for expected, ranked in materialized)
        / len(materialized),
        mean_reciprocal_rank=sum(
            reciprocal_rank(expected, ranked) for expected, ranked in materialized
        )
        / len(materialized),
        ndcg_at_k=sum(ndcg_at_k(expected, ranked, k) for expected, ranked in materialized)
        / len(materialized),
    )
