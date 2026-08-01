from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TypedDict

from opspilot.corpus import load_markdown_documents
from opspilot.domain.models import SearchHit
from opspilot.evaluation.metrics import summarize
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.retrieval.service import HybridRetriever


class GoldenCase(TypedDict):
    id: str
    query: str
    expected_document_ids: list[str]


def unique_document_ranking(hits: list[SearchHit]) -> list[str]:
    ranked: list[str] = []
    for hit in hits:
        document_id = hit.chunk.document_id
        if document_id not in ranked:
            ranked.append(document_id)
    return ranked


def main() -> None:
    retriever = HybridRetriever(HashEmbeddingProvider())
    retriever.index_documents(load_markdown_documents(Path("fixtures/runbooks")))

    evaluated = []
    with Path("evals/golden_queries.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            case: GoldenCase = json.loads(line)
            hits = retriever.search(case["query"], top_k=5)
            ranked = unique_document_ranking(hits)
            evaluated.append((set(case["expected_document_ids"]), ranked))

    summary = summarize(evaluated, k=3)
    print(json.dumps(asdict(summary), indent=2, sort_keys=True))

    if summary.recall_at_k < 1.0 or summary.mean_reciprocal_rank < 0.9:
        raise SystemExit("retrieval evaluation failed the foundation thresholds")


if __name__ == "__main__":
    main()
