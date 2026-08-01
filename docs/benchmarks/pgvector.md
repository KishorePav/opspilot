# PostgreSQL retrieval benchmark contract

The milestone 2 benchmark is a reproducible engineering baseline for the
persistence adapter. It is not evidence of production traffic, customer data,
or internet-scale performance.

## Workload

- PostgreSQL 17 with the pgvector extension
- 500 generated documents in CI by default
- one 1,536-dimension deterministic hash embedding per document
- five incident families distributed across five service metadata values
- service-filtered full-text and HNSW candidate retrieval
- database-side reciprocal-rank fusion
- five warm-up queries followed by 50 measured queries

Every query verifies that its highest-ranked evidence satisfies the requested
service filter. Generated rows carry a unique benchmark-run identifier and are
removed after measurement.

## Reproduce

```bash
docker compose up -d postgres
make migrate
make benchmark-db
```

The command writes `artifacts/benchmarks/pgvector-ci.json` with:

- corpus and embedding dimensions;
- indexing duration;
- mean, p50, p95, and p99 query latency;
- calculated queries per second;
- an explicit synthetic-baseline scope statement.

GitHub Actions runs the same command against `pgvector/pgvector:pg17` and
uploads the JSON as the `pgvector-benchmark` workflow artifact. Hardware,
concurrency, caches, network placement, corpus size, and vector distribution
all affect the numbers, so results from different environments must not be
compared without recording those variables.
