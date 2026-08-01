# Build roadmap

| Milestone | Evidence produced | Portfolio status |
|---|---|---|
| 1. Retrieval foundation | Unit tests, golden dataset, Recall@K/MRR/nDCG, API contract | Complete |
| 2. pgvector integration | Migration, filtered hybrid queries, integration tests, latency baseline | Implemented |
| 3. Single investigator agent | Typed read-only tools, structured diagnosis, cited evidence | Planned |
| 4. Safety and evaluation | Injection tests, trace graders, regression gates, failure taxonomy | Planned |
| 5. Approval workflow | Durable run state, dry-run remediation, explicit approval, audit record | Planned |
| 6. Production operations | Deployment, OpenTelemetry, dashboards, SLOs, cost/latency reports | Planned |

Milestone status changes only after its acceptance checks are reproducible in CI
or the documented integration environment.
