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
