# ADR 0002: Execute filtered hybrid retrieval in PostgreSQL

- Status: Accepted
- Date: 2026-08-01

## Context

The foundation retriever ranks an in-memory corpus deterministically, which is
valuable for unit tests and evaluation but cannot demonstrate durable ingestion
or bounded-memory production behavior. Splitting lexical retrieval, vector
retrieval, metadata filtering, and fusion across separate services would add
operational dependencies before retrieval quality has outgrown one datastore.

Metadata filters also need to constrain both candidate sets before ranking. A
filter applied only after approximate vector search can omit relevant evidence
or leak cross-scope candidates into fusion.

## Decision

Use PostgreSQL 17 with pgvector as the first persistent retrieval store.

- Store content, JSON metadata, a generated `tsvector`, and 1,536-dimension
  embeddings in one evidence table.
- Use GIN indexes for full-text and metadata containment and HNSW with cosine
  distance for vector candidates.
- Apply the same parameterized JSON containment predicate inside both candidate
  queries.
- Fuse bounded lexical and semantic ranks in SQL using weighted
  reciprocal-rank fusion.
- Keep the in-memory implementation for offline tests and retain a common
  retrieval protocol at the API boundary.
- Run embeddings before opening the replacement transaction, then delete stale
  chunks and insert the new document version atomically.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Dedicated vector database | Adds another service and consistency boundary before scale requires it |
| OpenSearch for both modes | Strong future hybrid option, but heavier for the first persistent slice |
| Application-side fusion | Transfers larger candidate sets and duplicates filter enforcement |
| Post-filtering vector results | Can reduce recall and does not establish a safe scope boundary |

## Consequences

- The API process no longer loads the entire persistent corpus.
- Ingestion and query behavior can be exercised against a real pgvector image
  in CI.
- A fixed schema dimension couples this milestone to 1,536-dimension embeddings;
  changing it requires a migration or a new embedding column/version.
- PostgreSQL metadata filters remain retrieval constraints, not authorization.
- HNSW recall and tuning need a larger corpus benchmark before scale claims are
  appropriate.
