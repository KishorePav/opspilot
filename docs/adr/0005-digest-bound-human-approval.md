# ADR 0005: Bind human approval to a durable remediation-plan digest

- Status: Accepted
- Date: 2026-08-02

## Context

The investigator consumes untrusted runbooks, logs, and model output. Giving it
a mutating tool would allow generated or injected text to cross directly into
a side effect. A simple `approved=true` flag is also unsafe: the plan could
change after review, approvals could remain valid indefinitely, and retries
could execute the same action more than once.

The workflow must remain reviewable in credential-free CI and demonstrate
production backend concerns without pretending that a public fixture is a real
operations provider.

## Decision

Keep all remediation outside the model/tool loop. A completed, diagnosed run
may accept one typed `restart_deployment` proposal when its service,
environment, and evidence IDs belong to that run. The registered executor first
returns a dry-run preview and performs no side effect.

Canonical JSON containing the plan version, run ID, and typed action is hashed
with SHA-256. A separate human actor approves or rejects that exact digest.
Approval is immutable, expires after a bounded interval, and cannot be supplied
by the proposal author.

At execution time, PostgreSQL locks the proposal and its run, recomputes the
digest, checks the unexpired approval, and creates one execution row plus one
audit event in the same transaction. The schema enforces one execution per
proposal and one owner per idempotency key. Replaying the same key returns the
stored result; a different key fails closed.

Each workflow transition appends an event containing the previous hash. The
event hash covers run, sequence, type, actor, payload, parent hash, and time.
Database triggers reject update and delete operations on audit rows, while
application verification detects missing, reordered, or modified events.

OpenAI's current guidance distinguishes automatic guardrails from human review
and recommends pausing before side effects such as edits, cancellations, shell
commands, and sensitive actions. The custom Responses API loop means OpsPilot
owns this durable pause and state transition rather than delegating it to a
provider runtime: https://developers.openai.com/api/docs/guides/agents/guardrails-approvals

## Alternatives considered

| Alternative | Why not chosen |
|---|---|
| Give the investigator a restart tool | Untrusted model/evidence text would sit too close to side effects |
| Approve by proposal ID only | Does not prove the reviewed plan is still the plan being executed |
| Store approval only in memory | Loses decisions and idempotency ownership across process restarts |
| Let the author approve | Removes separation of duties and weakens the portfolio's safety contract |
| Retry the executor without a persistent key | Can duplicate side effects after network/process ambiguity |
| Integrate a real cloud or Kubernetes mutation now | Would require credentials, authenticated RBAC, recovery, and operational safeguards outside this public milestone |

## Consequences

- Model output can recommend an action but cannot authorize or execute it.
- Reviewers can identify the exact bytes and evidence bound to a decision.
- Database constraints and atomic transitions protect retries across processes.
- The audit stream is tamper-evident and row-append-only for the application.
- The public demo is safe because execution is synthetic and environment-bound.
- Production identity, provider credentials, RBAC, claim leases/recovery,
  observability, and a real remediation adapter remain explicit follow-up work.
