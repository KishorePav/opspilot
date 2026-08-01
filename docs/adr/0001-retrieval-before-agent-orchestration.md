# ADR 0001: Measure retrieval before agent orchestration

- Status: Accepted
- Date: 2026-08-01

## Context

An incident investigator can produce fluent but unsupported diagnoses when its
evidence retrieval is weak. Starting with multiple agents would add orchestration
complexity before the evidence path can be measured.

## Decision

Build and evaluate a provider-independent hybrid retrieval system first. Use a
single investigator agent only after a golden-query suite establishes a baseline.
Do not introduce agent handoffs in the initial implementation.

## Consequences

- Retrieval failures can be separated from generation failures.
- Offline tests remain deterministic and require no model credentials.
- Agent functionality arrives later than a chatbot-style demo.
- The same retrieval contract can support different embedding and agent
  providers without changing domain logic.
