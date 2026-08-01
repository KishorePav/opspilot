# ADR 0006: Authenticate actors and fence recoverable execution leases

- Status: Accepted
- Date: 2026-08-02

## Context

Milestone 5 accepted actor objects from request JSON and left an execution in
`executing` forever if its process died after the database claim. It also had no
production telemetry or deployable security baseline. Those gaps were coupled:
recovery is unsafe without a trustworthy requester and observable ownership,
and telemetry is unsafe if it copies incident content or identity into labels.

## Decision

Every `/v1` request must carry an asymmetric OIDC access token. OpsPilot obtains
the signing key from an HTTPS JWKS endpoint and validates a fixed RS256/ES256
allowlist, issuer, audience, expiry, issued-at time, subject, actor type, tenant,
and known roles. Endpoint dependencies enforce role policy. Workflow actors and
tenant scope come from the verified principal; request JSON cannot override
them. Cross-tenant resources return the same not-found response as absent IDs.

Execution claims receive a server-owned worker ID, lease expiry, attempt count,
and monotonically increasing fencing token. A retry with the same idempotency
key may recover only an expired executing claim. Recovery increments the token
and appends an audit event. Completion, failure, and heartbeat transitions lock
the record and require the current worker, fencing token, and unexpired lease.

Manual OpenTelemetry instruments use route templates and bounded enums only.
The instrumentation boundary rejects unregistered operation attributes. It
does not record incident summaries, retrieved content, evidence IDs, actor IDs,
tenant IDs, prompts, bearer tokens, or provider exception text. The collector
deletes authorization and end-user attributes again before export.

## Alternatives considered

- Trust actor JSON behind an API gateway: rejected because an accidental direct
  route or gateway-policy drift would turn user input into authorization.
- Use long-lived API keys: rejected because they lack issuer, audience, expiry,
  human/service classification, tenant, and rotation semantics.
- Recover timed-out work without fencing: rejected because an old worker could
  complete after a new worker had taken ownership.
- Put incident IDs or tenant IDs in metric labels: rejected because of privacy
  and unbounded cardinality.
- Deploy a real Kubernetes remediation client now: rejected because the public
  project has no real cluster, workload identity, or provider acceptance suite.

## Consequences

Identity-provider and JWKS availability become production dependencies.
Readiness fails unless authentication configuration and PostgreSQL are
available. Executors longer than the lease must renew it; an expired worker
fails closed. Provider-side idempotency remains mandatory because a process may
die after an external side effect but before persisting the outcome.

The Kubernetes network policy permits generic HTTPS because standard
NetworkPolicy cannot select external FQDNs. A real environment must replace
that rule with a gateway, proxy, service mesh, or CNI FQDN policy scoped to the
identity provider, OpenAI, and trace backend.
