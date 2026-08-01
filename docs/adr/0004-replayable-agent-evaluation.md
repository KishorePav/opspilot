# ADR 0004: Gate the investigator with replayable traces and deterministic graders

- Status: Accepted
- Date: 2026-08-01

## Context

Milestone 3 established one bounded agent and proved individual invariants with
unit tests. It did not provide a representative dataset that could answer
whether a prompt, schema, tool, or budget change improved or regressed the
workflow end to end. Live-model-only tests would also be nondeterministic,
credential-dependent, and unsuitable as the required pull-request gate.

Prompt injection requires workflow-level evidence. A unit test that searches
for suspicious words cannot prove what tools were selected, whether the runtime
executed them, which evidence entered the ledger, or what appeared in the final
report.

## Decision

Store representative investigation cases as versioned JSONL. Each case records:

- a validated incident request;
- replayed typed model turns and provider-shaped token usage;
- investigator budgets and an optional versioned pricing policy;
- expected terminal outcome, trace events, evidence, citations, safety
  behavior, and resource ceilings.

Replay those turns through the production orchestrator and registered read-only
tools. Grade the resulting report, evidence ledger, partial or complete trace,
typed failure, and usage summary. CI fails when aggregate thresholds regress
and uploads the full machine-readable report.

The initial dataset includes successful diagnosis with malicious text present,
invented citations, scope expansion, duplicate queries, an injection-driven
unregistered remediation request, and evidence-budget overflow.

This mirrors current OpenAI guidance to use traces to understand tool and policy
behavior, then promote representative traces into repeatable datasets and eval
runs. See [agent evaluations](https://developers.openai.com/api/docs/guides/agent-evals),
[trace grading](https://developers.openai.com/api/docs/guides/trace-grading), and
[agent safety](https://developers.openai.com/api/docs/guides/agent-builder-safety).

## Cost-accounting rule

Responses API usage exposes input, output, and total token counts, with cached
and reasoning details where available. The adapter normalizes those fields per
model call. Cost is estimated only when a policy provides an exact model,
version label, and input, cached-input, and output rates. A rate/model mismatch
fails instead of silently applying the wrong price.

Checked-in rates are labelled `synthetic-eval-rates-v1`. They validate the
accounting and budget gate; they are not vendor pricing.

## Failure taxonomy

Every fail-closed terminal outcome uses a registered code with one category,
retryability decision, and sanitized public message. Expected tool-boundary
errors use the same registry. Partial trace, evidence, and usage are attached to
the internal failure for evaluation, while the API exposes only code, category,
retryability, and safe text.

## Alternatives considered

| Alternative | Why not chosen |
|---|---|
| Live-model cases as required CI | Nondeterministic, costs money, needs secrets, and can fail for provider availability |
| Model-as-judge only | Adds another nondeterministic model without first enforcing objective safety and citation invariants |
| Unit tests only | Do not provide versioned scenario coverage or end-to-end aggregate metrics |
| Store only final answers | Cannot grade tool choice, containment, budgets, or why a workflow failed |
| Hard-code provider prices | Becomes silently stale and turns evaluation evidence into an unsupported cost claim |

## Consequences

- Pull requests get a fast, credential-free workflow regression signal.
- Adversarial model behavior can be replayed safely and containment is visible.
- Token and cost-policy regressions are reviewable beside quality regressions.
- The suite measures the checked-in traces and application boundary; it does
  not establish current live-model diagnosis accuracy.
- A later opt-in live evaluation can record new candidate traces, but those
  traces must be reviewed before becoming deterministic baselines.
