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

Milestone 3 adds one provider-independent investigation loop. The model may
select only registered read-only tools. The application validates their typed
arguments, constrains operational queries to the incident service, environment,
and time window, and adds successful results to an evidence ledger. The model
can submit a final Pydantic-validated report only after those calls. The
orchestrator rejects unknown evidence IDs, out-of-scope affected services,
duplicate calls, and exhausted budgets.

The OpenAI Responses API is one adapter behind the investigation gateway. Each
turn reconstructs its bounded state from the incident request, evidence ledger,
and sanitized tool trace. This avoids provider-owned orchestration state and
keeps deterministic gateways usable in CI, at the cost of repeating context on
each live turn.

Milestone 4 adds a replayable evaluation boundary around that unchanged agent.
Each JSONL case contains an incident request, model-selected turns, token usage,
budgets, and expected behavior. The replay gateway drives the real
orchestrator and tools; deterministic graders then inspect terminal outcome,
tool traces, collected evidence, citations, injected-text propagation, and
resource use. Hard thresholds turn those grades into a CI regression gate.

Provider usage is normalized into input, cached-input, output, reasoning, and
total token fields. Dollar cost remains optional: the estimator operates only
with an explicit model, three rates, and version label. Checked-in evaluation
rates are intentionally synthetic and cannot be presented as provider pricing.

## Component responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| Chunker | Stable, overlapping evidence units | Call models or databases |
| Embedding provider | Convert text to vectors | Rank or synthesize answers |
| BM25 index | Lexical ranking | Infer semantic similarity |
| Fusion | Combine independent ranked lists | Hide source attribution |
| Retriever | Apply filters and return evidence | Produce a diagnosis |
| Evaluation | Grade retrieval and agent traces against versioned datasets | Use production secrets or hidden expectations |
| API | Validate requests and serialize evidence | Contain ranking logic |
| PostgreSQL adapter | Persist chunks and execute filtered hybrid queries | Synthesize answers |
| Migration runner | Apply immutable, checksum-verified schema changes | Modify applied files |
| Investigator | Enforce tool, scope, evidence, and round budgets | Execute remediation |
| Model gateway | Choose a read tool or submit a typed report | Execute tools directly |
| Tool registry | Validate calls and return evidence records | Expose generic shell, SQL, or HTTP |
| Evidence ledger | Record tool-derived IDs and validate citations | Treat model claims as evidence |
| Operational adapter | Perform bounded read queries | Expand incident scope or mutate systems |
| Usage accounting | Normalize provider tokens and apply explicit versioned rates | Guess current pricing |
| Failure taxonomy | Classify sanitized terminal and trace errors | Expose provider or internal exception text |

## Planned production flow

1. Ingestion validates source, tenant, sensitivity, and metadata.
2. Chunking creates stable evidence identifiers.
3. Embeddings are generated in bounded batches with retries and rate limits.
4. PostgreSQL stores text, metadata, generated full-text vectors, and embeddings.
5. Retrieval applies tenant and service filters before ranking.
6. The investigator selects typed read-only tools inside bounded budgets.
7. Successful tool results enter the evidence ledger with stable source IDs.
8. A structured report is accepted only when every cited ID exists in the ledger.
9. Evaluation and tracing record retrieval, tool, citation, safety, latency,
   token, cost-policy, and outcome signals.
10. Any remediation request interrupts execution for human approval.

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
- Unknown tools and invalid arguments create sanitized failed trace events.
- Repeated calls, unknown citations, report scope violations, and exhausted
  budgets stop the investigation without returning an unsupported diagnosis.
- Terminal failures carry a stable code, category, retryability flag, partial
  trace, partial evidence ledger, and usage summary for grading; public API
  responses expose only the sanitized subset.
- Evaluation cases may intentionally trigger a forbidden tool request. Passing
  requires that the unregistered call is observable and never succeeds.

## Trust boundaries

Runbooks, logs, alerts, and tool outputs are untrusted data. They cannot change
system instructions or authorize tools. Credentials stay server-side and tools
receive narrowly scoped identities. Public fixtures are synthetic.

The current operational source is a synthetic JSON fixture. Production log,
deployment, and metric adapters still require authentication, RBAC or tenant
enforcement, timeouts, pagination, and provider-specific availability handling.
