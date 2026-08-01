# Production SLO contract

These objectives define how a real deployment should be measured. They are not
claims that OpsPilot has production users or a 30-day measurement history.

| Signal | Initial objective | Window | Exclusions |
|---|---:|---:|---|
| Authenticated `/v1` availability | 99.9% non-5xx | 30 days | 4xx policy and validation decisions |
| Non-agent workflow latency | 95% under 500 ms | 30 days | investigation/model duration |
| Investigation completion | 99% terminal response | 30 days | caller cancellations and invalid input |
| Approved remediation terminal outcome | 99.5% | 30 days | rejected/expired/unapproved plans |
| Unauthorized or stale execution commits | 0 | Always | None |
| Audit-chain verification | 100% | Always | None |

The Prometheus rules provide a five-minute availability ratio, p95 HTTP
duration, a fast availability-burn alert, a workflow-error alert, and an alert
for any lease recovery. Lease recovery is not automatically an error: it is an
operational signal that requires investigation because the earlier worker may
have failed around a side-effect boundary.

The dashboard shows only bounded aggregate dimensions: route template, HTTP
method/status, workflow operation/outcome, authentication decision reason,
lease-recovery count, and token type. Incident, evidence, identity, tenant,
prompt, and credential data are prohibited from telemetry.

Before production use, load tests must choose histogram buckets around the
actual latency objectives, alerts must use multi-window error-budget burn
rates, and the team must define ownership, paging hours, escalation, and an SLO
review cadence. Provider availability and live-model quality require separate
SLIs because an HTTP success can still contain an insufficient or incorrect
diagnosis.
