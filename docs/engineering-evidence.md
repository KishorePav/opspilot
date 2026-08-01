# Engineering evidence policy

This repository is intended to demonstrate decisions and verified engineering
work, not contribution volume.

## Accepted evidence

- passing unit, integration, and security tests;
- versioned evaluation datasets and reproducible metrics;
- load-test inputs, environment details, and percentile results;
- architecture decision records with alternatives and consequences;
- runnable demos whose limitations are stated;
- CI results tied to the commit being discussed.

## Rejected evidence

- fabricated users, revenue, customer deployments, incidents, or scale;
- unsupported accuracy and latency claims;
- backdated commits or generated micro-commits intended to simulate duration;
- private employer artifacts presented as public project work;
- screenshots without a reproducible command or documented environment.

Fast implementation is not itself suspicious. The proof is whether the author
can explain the trade-offs, reproduce the results, diagnose failures, and extend
the system under interview conditions.

## Milestone 3 acceptance evidence

The single-investigator milestone is accepted only when automated tests prove:

- a model-selected sequence can collect runbook, log, deployment, and metric
  evidence and return a typed report;
- every cited ID belongs to the successful-call evidence ledger;
- invented citations fail closed;
- service and environment scope cannot expand beyond the incident request;
- repeated calls and bounded-resource exhaustion cannot loop indefinitely;
- model-provider credentials are unnecessary for the unit and API test suites.

These tests prove contracts and failure behavior. They do not prove live-model
diagnostic accuracy, production security, or customer impact.

## Milestone 4 acceptance evidence

The safety-and-evaluation milestone is accepted only when:

- versioned JSONL cases replay both supported diagnoses and fail-closed paths;
- graders inspect outcome, tool trace, required evidence, citation precision,
  required-citation recall, injected-text propagation, and resource budgets;
- malicious evidence cannot make an unregistered remediation tool succeed;
- invented citations, duplicate calls, scope violations, and evidence-budget
  overflow produce the expected typed failure or contained trace event;
- token usage is normalized per model call and optional cost uses an explicit,
  versioned price policy;
- CI enforces checked-in thresholds and publishes the complete JSON result.

The current six-case replay suite is deterministic and credential-free. Its
rates are synthetic; it does not prove live-model accuracy or quote current
provider pricing.

## Milestone 5 acceptance evidence

The durable approval milestone is accepted only when automated tests prove:

- completed and failed investigations can be persisted independently of an API
  process;
- a remediation cannot expand service/environment scope or cite evidence that
  the investigation did not collect;
- the dry run performs no side effect and the canonical plan has a stable digest;
- the proposal author cannot approve the same plan and non-human actors cannot
  supply approval;
- changed, rejected, unapproved, and expired plans never reach the executor;
- one persistent idempotency key invokes the executor once across store/process
  recreation, while a conflicting key fails closed;
- audit hashes detect modified history and PostgreSQL rejects audit row updates;
- API errors remain typed and sanitized.

The checked-in executor is intentionally simulated. These checks prove policy,
state-transition, idempotency, and audit contracts; they do not prove a real
Kubernetes/cloud integration, authenticated RBAC, or production recovery.

## Milestone 6 acceptance evidence

The production-operations milestone is accepted only when automated checks
prove:

- asymmetric tokens validate fixed algorithms, signature keys, issuer,
  audience, lifetime, subject, actor type, tenant, and known roles;
- missing credentials and insufficient roles fail before protected endpoint
  work, and request JSON can no longer choose the actor;
- cross-tenant run and proposal identifiers return not-found responses;
- an expired execution lease is recoverable with the same idempotency key and a
  higher fencing token, while its stale worker cannot commit;
- telemetry accepts only registered bounded attributes and excludes incident,
  evidence, identity, tenant, prompt, token, and credential content;
- deployment validation checks non-root/read-only execution, dropped
  capabilities, probes, resources, disruption protection, scaling, network
  policy, collector privacy actions, alerts, and dashboard structure;
- CI builds the runtime container and its unauthenticated liveness probe passes.

These checks prove configuration and contract behavior. They do not prove a
live identity-provider integration, real remediation provider, production
traffic, 30-day SLO attainment, or live-model diagnostic quality.

## Milestone 7 acceptance evidence

The controlled-evaluation and demo milestone is accepted when automated checks
prove:

- normal tests, pull requests, and container startup cannot trigger a provider
  request or consume credits;
- the live runner requires both `--confirm-live-api` and a runtime-only
  `OPENAI_API_KEY`;
- every live case bounds rounds, tools, evidence, total tokens, per-call output,
  timeout, retries, and selected-case count;
- the artifact records a dataset digest, requested and observed model names,
  the complete synthetic evidence/trace, citations, latency, actual tokens, and
  grades;
- dollar estimates remain absent unless a complete versioned price policy is
  supplied;
- the demo runs the real bounded investigator but accepts only one allowlisted
  replay case and exposes no arbitrary prompt or remediation route;
- the demo container builds and its scenario endpoint passes a hosted smoke
  test.

These checks establish a safe path for collecting live evidence and a
deployable portfolio demonstration. They do not themselves establish a
live-model pass rate. That claim requires an artifact from the protected manual
workflow tied to a commit and model identifier.
