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

Native OpenAI Responses API and Google Gen AI adapters sit behind the same
investigation gateway. Each turn reconstructs its bounded state from the
incident request, evidence ledger, and sanitized tool trace. This avoids
provider-owned orchestration state and keeps deterministic gateways usable in
CI, at the cost of repeating context on each live turn.

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

Milestone 5 adds a durable workflow after the investigator, not a write tool
inside it. A completed diagnosis can produce a typed remediation proposal only
when the service, environment, and cited evidence remain inside the original
incident. The executor first returns a side-effect-free preview. OpsPilot then
hashes the canonical plan and persists that digest with the proposal.

A different human actor must approve the exact digest before its short expiry.
PostgreSQL locks the proposal, recomputes the digest, verifies the decision, and
creates one execution claim and audit event in a single transaction. A unique
idempotency key and one-execution-per-proposal constraint prevent duplicate
side effects across retries or process restarts. Audit events form a per-run
SHA-256 chain and database triggers reject row updates and deletes.

Milestone 6 moves actor and tenant authority to verified OIDC access tokens.
The JWKS adapter fixes the accepted asymmetric algorithms and validates issuer,
audience, expiry, issued-at, subject, actor type, tenant, and roles. FastAPI
dependencies enforce endpoint RBAC, while the workflow service independently
checks every retrieved run or proposal against the principal tenant. Another
tenant receives a not-found response rather than resource-existence evidence.

Execution claims now have a worker owner, expiry, attempt count, and fencing
token. The same idempotency key can recover an expired claim; the transaction
increments the token and extends the audit chain. A completion, failure, or
heartbeat using an earlier token, another worker, or an expired lease fails.

Manual OpenTelemetry spans and metrics cover HTTP, authentication, workflow
operations, model-token totals, and lease recovery. Only route templates and
bounded outcome fields are accepted. Incident content, evidence, identities,
tenants, prompts, credentials, and provider exception text never cross the
telemetry interface. A validated container and Kubernetes base add probes,
non-root execution, a read-only filesystem, dropped capabilities, resource
bounds, disruption protection, scaling, and network-policy scaffolding.

Milestone 7 separates model measurement from public demonstration. The live
evaluator invokes an explicitly selected provider gateway only after a CLI
confirmation and matching runtime credential check. Versioned synthetic inputs pass
through the same investigator and deterministic graders, with per-call output
limits, provider timeout, no SDK retries, and a cumulative token fence. Its
artifact identifies the exact dataset bytes and observed provider model; cost
is unknown unless a complete versioned price policy is supplied.

The public demo is a different FastAPI application and container target. It
loads one allowlisted replay case and invokes the real investigator, retrieval,
tools, evidence ledger, and citation validation. It does not import a live
gateway into its request path and exposes no arbitrary incident input,
authentication bypass for `/v1`, workflow store, or executor. This makes the
demo useful for inspection without turning a portfolio URL into a funded model
proxy or side-effect surface.

Milestone 8 makes the live boundary provider-neutral in practice. The OpenAI
and Gemini adapters translate only tool declarations, function-call results,
and usage accounting; the orchestrator still owns scope, duplicate detection,
evidence, citations, budgets, and terminal validation. Gemini automatic
function execution is disabled. Provider/model mismatches fail before a client
is constructed, and failed calls retain only bounded diagnostics suitable for
the evaluation artifact—never raw exception text, prompts, or credentials.

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
| Workflow service | Enforce scope, evidence, separation of duties, expiry, and audit verification | Trust model output or request text as approval |
| Workflow store | Persist state and apply atomic transitions | Execute remediation or weaken policy |
| Human decision | Approve or reject one immutable plan digest | Approve changed or expired plans |
| Remediation executor | Preview and execute one registered action | Expose shell, generic HTTP, SQL, or model access |
| Audit chain | Make workflow history tamper-evident and append-only | Authorize an action by itself |
| OIDC authenticator | Validate signing key and required identity claims | Choose policy or trust token algorithms dynamically |
| RBAC dependency | Map verified roles to one endpoint capability | Accept actors or tenants from request JSON |
| Tenant guard | Hide cross-tenant runs and proposals | Use retrieval metadata as authorization |
| Execution lease | Recover abandoned work with an incremented fence | Permit a stale worker to commit |
| Telemetry boundary | Emit bounded operational signals | Export content, identity, prompts, tokens, or credentials |
| Live evaluator | Measure selected versioned cases with explicit runtime consent and budgets | Run in ordinary CI or infer provider pricing |
| Synthetic demo | Replay one allowlisted case through real safety contracts | Accept arbitrary prompts, call a model, or expose remediation |

## Production reference flow

1. Authentication validates the token signature, issuer, audience, lifetime,
   actor type, tenant, and role.
2. Ingestion validates source, tenant, sensitivity, and metadata.
3. Chunking creates stable evidence identifiers.
4. Embeddings are generated in bounded batches with retries and rate limits.
5. PostgreSQL stores text, metadata, generated full-text vectors, and embeddings.
6. Retrieval applies tenant and service filters before ranking.
7. The investigator selects typed read-only tools inside bounded budgets.
8. Successful tool results enter the evidence ledger with stable source IDs.
9. A structured report is accepted only when every cited ID exists in the ledger.
10. Evaluation and tracing record retrieval, tool, citation, safety, latency,
    token, cost-policy, and outcome signals.
11. A human-authored typed proposal cites evidence from the completed diagnosis.
12. A dry run produces a preview without side effects and the plan is hashed.
13. A separate human approves or rejects that exact digest before expiry.
14. PostgreSQL creates a leased execution claim with an idempotency key and
    fencing token.
15. The bounded executor records the outcome only while it owns the live fence;
    every transition extends the tamper-evident audit chain.
16. OpenTelemetry records bounded outcome and latency signals without content
    or identity attributes.

## Failure and consistency behavior

- Embeddings are validated for count and dimension before a database write.
- Re-indexing a document deletes stale chunks and inserts replacements in one
  transaction; readers see the old or new version, never a partial replacement.
- Metadata filters use bound JSON values. They are a retrieval constraint, not
  an authorization system; durable workflow tenancy is enforced separately
  from token claims and persisted run ownership.
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
- Changed plan data cannot reuse an earlier decision because the digest is
  recomputed inside the locked approval and execution transitions.
- Rejected, unapproved, expired, self-approved, out-of-scope, and uncited plans
  fail before the executor is invoked.
- A repeated idempotency key returns the stored terminal execution; a different
  key for the same proposal fails instead of creating another action.
- An executing claim can be recovered only after its lease expires and only
  with the same idempotency key. Recovery increments the fencing token; stale
  completion, failure, and heartbeat attempts fail.
- Audit verification fails on missing, reordered, reparented, or modified
  events. Audit rows reject application-level updates and deletes.
- Missing, invalid, wrongly scoped, expired, or insufficient-role tokens fail
  before the endpoint invokes the domain workflow.

## Trust boundaries

Runbooks, logs, alerts, and tool outputs are untrusted data. They cannot change
system instructions or authorize tools. Credentials stay server-side and tools
receive narrowly scoped identities. Public fixtures are synthetic.

The current operational source is a synthetic JSON fixture. Production log,
deployment, and metric adapters still require provider-specific identity,
timeouts, pagination, tenant-aware queries, and availability handling.

The remediation executor is also synthetic and only accepts the `synthetic`
environment. Actors and tenants are now bound to authenticated principals, but
production execution still requires a least-privilege provider identity,
provider-side idempotency, timeout and retry rules, and workload-specific
policy. The checked-in deployment and SLOs are validated reference artifacts,
not evidence of a live production deployment.
