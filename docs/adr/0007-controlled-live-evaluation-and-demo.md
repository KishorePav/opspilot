# ADR 0007: Separate live evaluation from the public demo

- Status: accepted
- Date: 2026-08-02

## Context

The first six milestones prove deterministic retrieval, agent safety,
approval, recovery, authentication, telemetry, and deployment contracts. They
do not prove how a current model behaves, and exposing the production
investigation endpoint as a portfolio demo would create a funded arbitrary
prompt surface with unnecessary credentials and workflow authority.

## Decision

Use two independent execution paths.

The live evaluator is an opt-in command and manual protected GitHub workflow.
It runs versioned synthetic cases through the production gateway and real
grader boundary, but only after explicit consent and runtime credential checks.
Provider calls have output and timeout limits, retries are disabled, and the
orchestrator enforces cumulative token caps. The artifact binds results to the
dataset digest, selected cases, requested and observed models, trace, citations,
latency, and token usage. Pricing is never inferred.

The public demo is a separate FastAPI app and container target. It accepts only
an allowlisted replay scenario and calls the real deterministic investigator,
retrieval tools, evidence ledger, and citation validator. It has no arbitrary
prompt, live gateway, database, identity, proposal, approval, execution, or
audit endpoint.

## Consequences

- Ordinary CI remains credential-free and deterministic.
- A public portfolio URL cannot consume model credits or reach remediation.
- The demo proves system behavior and explainability, not current model quality.
- A live-quality claim requires a protected workflow artifact tied to a commit,
  dataset digest, and model identifier.
- Two application surfaces require separate smoke tests and deployment docs.

## Rejected alternatives

- Run live calls on every pull request: rejected because untrusted changes could
  consume secrets and variable model behavior would make CI nondeterministic.
- Put a free-text live endpoint behind a client-side limit: rejected because
  client limits do not protect credits, tools, or abuse boundaries.
- Present deterministic replay scores as model accuracy: rejected because it
  would confuse contract testing with empirical provider behavior.

## References

- [OpenAI agent evaluations](https://developers.openai.com/api/docs/guides/agent-evals)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
