# ADR 0003: Use one bounded investigator with typed read-only tools

- Status: Accepted
- Date: 2026-08-01

## Context

Retrieval now produces stable evidence IDs through deterministic and persistent
adapters. The next risk is allowing a model to turn that evidence into a fluent
report without enforcing scope, tool permissions, budgets, or citations.

A framework-managed multi-agent graph would add handoffs and hidden state before
the behavior of one investigator has been measured. Giving a model a generic
HTTP, shell, or database tool would also make authorization and failure behavior
too broad for an incident-response reference implementation.

## Decision

Use one provider-independent investigation loop with four read-only tools:

- `search_runbooks` retrieves approved operational documentation;
- `search_logs` reads bounded log records;
- `list_deployments` reads bounded deployment history;
- `query_metrics` reads named metric samples.

Every operational call is constrained to a service, environment, and time range
from the validated incident request. Tool arguments use Pydantic-generated JSON
Schema, and tools validate again before execution. The orchestrator—not the
model—enforces round, call, and evidence budgets; blocks repeated calls; records
sanitized traces; and rejects service, environment, time, or citation scope
violations.

The OpenAI adapter uses Responses API function calling for tool selection and a
strict `submit_incident_report` function for the final report. The core loop is
defined by protocols and tested with deterministic scripted gateways, so unit
and CI tests require no model credential. Current OpenAI guidance distinguishes
function calling for connecting models to application tools from structured
outputs for typed model responses; the final submission function provides the
same schema-validated boundary inside the tool loop. See the official
[function-calling guide](https://developers.openai.com/api/docs/guides/function-calling)
and
[structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs).

Each model turn receives the bounded incident state again instead of relying on
provider-side conversation state. This costs more input tokens but keeps the
domain state auditable, reproducible, and provider-independent for this
milestone.

## Trust and evidence rules

- Runbooks, logs, metrics, deployments, and incident text are untrusted data.
- Evidence content cannot add tools, alter instructions, or authorize actions.
- Every timeline event, ranked hypothesis, probable root cause, and recommended
  next action requires one or more evidence IDs.
- A final report can cite only IDs recorded by successful tool calls.
- When evidence is insufficient, the report must omit a probable root cause and
  state concrete unanswered questions.
- The investigator has no remediation or other state-changing tool.

## Alternatives considered

| Alternative | Why not now |
|---|---|
| Multiple specialist agents | Adds handoff, state, and attribution complexity before one loop is evaluated |
| Generic shell or HTTP tool | Cannot prove least privilege or bounded side effects |
| Provider SDK as the domain orchestrator | Couples safety policy and tests to one vendor runtime |
| Deterministic fixed tool sequence | Easier to test, but does not demonstrate adaptive model-selected investigation |
| Persist provider conversation state | Saves repeated context but weakens explicit local state and replayability |

## Consequences

- The agent can choose evidence sources adaptively while application code keeps
  authority over execution.
- Citation hallucinations and scope expansion fail closed before a report is
  returned.
- CI can prove orchestration invariants without network access or API spend.
- The synthetic operational adapter demonstrates contracts, not production log
  or monitoring integration.
- Live-model answer quality, prompt-injection evaluation, trace grading, token
  cost, and recovery from provider rate limits remain milestone 4 work.
