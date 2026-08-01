# Investigation failure taxonomy

Stable codes let operators, graders, and APIs distinguish retryable dependency
failures from fail-closed policy outcomes without exposing raw exception text.

| Category | Example codes | Retry posture |
|---|---|---|
| `safety_policy` | `duplicate_tool_call`, `scope_violation`, `unknown_tool`, `report_contains_unknown_citation` | Do not retry unchanged input |
| `budget` | `tool_call_budget_exhausted`, `evidence_budget_exhausted`, `investigation_round_budget_exhausted`, `token_budget_exhausted` | Require a reviewed budget or workflow change |
| `contract` | `invalid_arguments`, `non_json_tool_arguments`, `report_incident_mismatch`, `pricing_policy_mismatch` | Correct the caller, model, or pricing contract |
| `data_integrity` | `evidence_id_collision` | Investigate the evidence source |
| `dependency` | `retrieval_unavailable` | Retry according to the dependency policy |
| `provider` | `model_gateway_failed` | Retry according to provider backoff and rate-limit policy |

The canonical code-to-category mapping lives in
`src/opspilot/investigation/failures.py`. Adding an emitted error code without a
registered definition is a contract error.

For `model_gateway_failed`, live evaluation artifacts may also include a
sanitized provider diagnostic: provider name, exception type, stable error
code, HTTP status, and request ID. Raw exception messages, request bodies,
prompts, evidence, and credentials are never included.
