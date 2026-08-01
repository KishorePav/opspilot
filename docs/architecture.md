# Architecture

## Current slice

The foundation milestone establishes the retrieval domain before an LLM is
allowed to synthesize a diagnosis. Documents are chunked deterministically,
embedded through a provider interface, ranked independently by lexical and
vector signals, then combined with weighted reciprocal-rank fusion.

The offline mode uses a deterministic hash embedder. It exists for tests,
repeatable evaluation, and local development—not as a claim of semantic-search
quality. The production adapter uses an external embedding provider and stores
vectors in PostgreSQL with pgvector.

## Component responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| Chunker | Stable, overlapping evidence units | Call models or databases |
| Embedding provider | Convert text to vectors | Rank or synthesize answers |
| BM25 index | Lexical ranking | Infer semantic similarity |
| Fusion | Combine independent ranked lists | Hide source attribution |
| Retriever | Apply filters and return evidence | Produce a diagnosis |
| Evaluation | Measure known-query retrieval | Use production secrets |
| API | Validate requests and serialize evidence | Contain ranking logic |

## Planned production flow

1. Ingestion validates source, tenant, sensitivity, and metadata.
2. Chunking creates stable evidence identifiers.
3. Embeddings are generated in bounded batches with retries and rate limits.
4. PostgreSQL stores text, metadata, full-text search vectors, and embeddings.
5. Retrieval applies tenant and service filters before ranking.
6. The investigator receives a bounded evidence bundle with source references.
7. Evaluation and tracing record retrieval, tool, latency, token, and outcome
   signals.
8. Any remediation request interrupts execution for human approval.

## Trust boundaries

Runbooks, logs, alerts, and tool outputs are untrusted data. They cannot change
system instructions or authorize tools. Credentials stay server-side and tools
receive narrowly scoped identities. Public fixtures are synthetic.
