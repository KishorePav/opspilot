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

Milestone 2 adds a PostgreSQL adapter without changing the in-memory retrieval
contract. Corpus ingestion embeds outside the database transaction, then
atomically replaces every chunk belonging to the affected document IDs. Failed
database writes therefore retain the last complete version of each document.

At query time, PostgreSQL applies the same JSON metadata containment filter to
both candidate sets before ranking. Full-text search and HNSW cosine search each
produce a bounded list; reciprocal-rank fusion combines their ranks and returns
the evidence fields without loading the whole corpus into the API process.

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
| PostgreSQL adapter | Persist chunks and execute filtered hybrid queries | Synthesize answers |
| Migration runner | Apply immutable, checksum-verified schema changes | Modify applied files |

## Planned production flow

1. Ingestion validates source, tenant, sensitivity, and metadata.
2. Chunking creates stable evidence identifiers.
3. Embeddings are generated in bounded batches with retries and rate limits.
4. PostgreSQL stores text, metadata, generated full-text vectors, and embeddings.
5. Retrieval applies tenant and service filters before ranking.
6. The investigator receives a bounded evidence bundle with source references.
7. Evaluation and tracing record retrieval, tool, latency, token, and outcome
   signals.
8. Any remediation request interrupts execution for human approval.

## Failure and consistency behavior

- Embeddings are validated for count and dimension before a database write.
- Re-indexing a document deletes stale chunks and inserts replacements in one
  transaction; readers see the old or new version, never a partial replacement.
- Metadata filters use bound JSON values. They are a retrieval constraint, not
  an authorization system; future tenant isolation must be enforced separately.
- Connection, pool, and statement failures cross the adapter boundary as a
  sanitized availability error and become HTTP 503 responses.
- Applied migration checksums are recorded. Editing a historical migration
  fails closed instead of silently changing the expected schema.
- A PostgreSQL advisory lock serializes concurrent migration runners.

## Trust boundaries

Runbooks, logs, alerts, and tool outputs are untrusted data. They cannot change
system instructions or authorize tools. Credentials stay server-side and tools
receive narrowly scoped identities. Public fixtures are synthetic.
