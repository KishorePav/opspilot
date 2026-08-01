# Build roadmap

| Milestone | Evidence produced | Portfolio status |
|---|---|---|
| 1. Retrieval foundation | Unit tests, golden dataset, Recall@K/MRR/nDCG, API contract | Complete |
| 2. pgvector integration | Migration, filtered hybrid queries, integration tests, latency baseline | Complete |
| 3. Single investigator agent | Typed read-only tools, structured diagnosis, cited evidence | Complete |
| 4. Safety and evaluation | Injection tests, trace graders, regression gates, failure taxonomy | Complete |
| 5. Approval workflow | Durable run state, dry-run remediation, explicit approval, audit record | Complete |
| 6. Production operations | OIDC/RBAC, tenant scope, fenced recovery, OpenTelemetry, hardened deployment, dashboard and SLO contract | Complete |

The checked-in deployment is a validated reference, not evidence that OpsPilot
has served production traffic. A future milestone may add a real provider only
after a least-privilege threat model, timeout and retry policy, staged rollout,
and provider-specific integration tests exist.

Milestone status changes only after its acceptance checks are reproducible in CI
or the documented integration environment.
