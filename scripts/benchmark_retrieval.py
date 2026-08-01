from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from pathlib import Path

import psycopg

from opspilot.adapters.postgres import PostgresHybridRetriever
from opspilot.config import Settings
from opspilot.domain.models import Document
from opspilot.retrieval.embedding import HashEmbeddingProvider
from opspilot.storage.migrations import apply_migrations

_SCENARIOS = (
    (
        "orders",
        "consumer lag increased after deployment and workers keep rebalancing",
        "Kafka consumer lag rises after deployment with repeated group rebalancing.",
    ),
    (
        "catalogue",
        "API latency rises while database connections are exhausted",
        "PostgreSQL connection pool exhaustion causes API latency and timeouts.",
    ),
    (
        "fulfilment",
        "pods restart with CrashLoopBackOff and exit code 137",
        "Kubernetes pods restart with CrashLoopBackOff after an out of memory kill.",
    ),
    (
        "payments",
        "webhook endpoint returns HTTP 500 and deliveries keep retrying",
        "Webhook deliveries receive HTTP 500 responses and enter a retry cycle.",
    ),
    (
        "analytics",
        "Dataflow cannot act as the worker service account",
        "Dataflow cannot impersonate its worker service account because IAM is missing.",
    ),
)


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    index = min(round((len(ordered) - 1) * percentile), len(ordered) - 1)
    return ordered[index]


def _documents(count: int, run_id: str) -> list[Document]:
    documents = []
    for index in range(count):
        service, _, content = _SCENARIOS[index % len(_SCENARIOS)]
        documents.append(
            Document(
                document_id=f"benchmark-{run_id}-{index:06d}",
                title=f"Synthetic {service} incident {index}",
                content=(
                    f"{content} This synthetic benchmark record is {index}; "
                    f"its deterministic discriminator is token-{index}."
                ),
                source="synthetic-benchmark",
                metadata={
                    "benchmark_run": run_id,
                    "environment": "benchmark",
                    "service": service,
                },
            )
        )
    return documents


def _cleanup(database_url: str, run_id: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "DELETE FROM evidence_chunks WHERE metadata @> %s::jsonb",
            (json.dumps({"benchmark_run": run_id}),),
        )


def run_benchmark(documents: int, iterations: int, output: Path | None) -> dict[str, object]:
    if documents < len(_SCENARIOS):
        raise ValueError(f"documents must be at least {len(_SCENARIOS)}")
    if iterations < 1:
        raise ValueError("iterations must be positive")

    settings = Settings.from_environment()
    apply_migrations(settings.database_url, Path("migrations"))
    run_id = uuid.uuid4().hex
    embedder = HashEmbeddingProvider(dimensions=1536)
    retriever = PostgresHybridRetriever(
        settings.database_url,
        embedder,
        pool_min_size=1,
        pool_max_size=4,
    )
    try:
        index_started = time.perf_counter()
        indexed_chunks = retriever.index_documents(_documents(documents, run_id))
        index_seconds = time.perf_counter() - index_started

        for service, query, _ in _SCENARIOS:
            retriever.search(query, top_k=5, filters={"service": service})

        samples_ms = []
        for iteration in range(iterations):
            service, query, _ = _SCENARIOS[iteration % len(_SCENARIOS)]
            started = time.perf_counter()
            hits = retriever.search(query, top_k=5, filters={"service": service})
            samples_ms.append((time.perf_counter() - started) * 1_000)
            if not hits or hits[0].chunk.metadata.get("service") != service:
                raise RuntimeError("benchmark retrieval violated its metadata filter")

        mean_ms = statistics.fmean(samples_ms)
        result: dict[str, object] = {
            "benchmark": "filtered-pgvector-hybrid-retrieval",
            "corpus_documents": documents,
            "embedding_dimensions": embedder.dimensions,
            "filtered": True,
            "index_seconds": round(index_seconds, 4),
            "indexed_chunks": indexed_chunks,
            "iterations": iterations,
            "mean_ms": round(mean_ms, 4),
            "p50_ms": round(_percentile(samples_ms, 0.50), 4),
            "p95_ms": round(_percentile(samples_ms, 0.95), 4),
            "p99_ms": round(_percentile(samples_ms, 0.99), 4),
            "queries_per_second": round(1_000 / mean_ms, 4),
            "scope": "synthetic CI/local baseline; not production performance",
        }
        rendered = json.dumps(result, indent=2, sort_keys=True)
        print(rendered)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
        return result
    finally:
        retriever.close()
        _cleanup(settings.database_url, run_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark filtered PostgreSQL retrieval")
    parser.add_argument("--documents", type=int, default=1_000)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    run_benchmark(arguments.documents, arguments.iterations, arguments.output)


if __name__ == "__main__":
    main()
