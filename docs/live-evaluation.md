# Controlled live-model evaluation

The live harness measures the existing bounded investigator against versioned
synthetic incidents. It is deliberately separate from deterministic CI and the
public demo.

## Invocation controls

The runner exits before constructing a provider client unless all of these are
true:

- `--confirm-live-api` is present;
- `--provider` is `openai` or `gemini`;
- the matching `OPENAI_API_KEY` or `GEMINI_API_KEY` exists at runtime;
- the model name passes a conservative character allowlist;
- the provider/model pair is compatible (`gemini-*` never routes to OpenAI);
- `--max-cases` is between one and ten;
- each dataset case has validated round, tool, evidence, and total-token caps.

The default command evaluates one case. Each provider call has a 30-second
timeout, a 4,096-output-token limit, low reasoning effort, and no SDK retries.
The orchestrator stops further progress when cumulative reported usage exceeds
the case token budget. A completed call may cross that fence, but no subsequent
tool or model call is allowed.

```bash
GEMINI_API_KEY='runtime-only' python scripts/run_live_agent_eval.py \
  --confirm-live-api \
  --provider gemini \
  --model gemini-3.6-flash \
  --max-cases 1
```

The default Gemini model is currently listed by Google as free of charge on the
Gemini Developer API free tier. Account billing and quota configuration remain
provider-side controls that OpsPilot cannot inspect. Use only the repository's
synthetic cases on a free-tier project with billing disabled when zero spend is
required.

## Artifact contract

`artifacts/evaluations/live-agent-eval.json` records:

- UTC generation time and total duration;
- requested provider, requested model, and provider-reported model identifiers;
- SHA-256 of the complete JSONL dataset and selected case IDs;
- structured report, evidence ledger, tool trace, grader details, and failure
  taxonomy when applicable;
- input, cached input, output, reasoning, and total tokens;
- sanitized provider diagnostics on failure: provider, exception type, stable
  error code, HTTP status, and request ID without raw exception text;
- estimated cost only when the caller supplied a model-matched version label
  and all three rates.

Artifacts contain only repository-owned synthetic data. A run should still be
reviewed before it is attached to a release or portfolio claim.

## GitHub workflow

The `Controlled live-model evaluation` workflow is manual only. Configure a
GitHub environment named `live-evaluation`, require a reviewer, and store
`GEMINI_API_KEY` as an environment secret for the free-tier default. Add
`OPENAI_API_KEY` only if paid OpenAI evaluation is intentionally enabled. The
provider selector injects only the selected credential. The job has read-only
repository permissions, evaluates one case by default, and uploads the JSON
artifact even when a grader threshold fails after the artifact was written.

Never add the live workflow to pull-request or `push` triggers. A successful
run establishes quality only for the selected dataset bytes, commit, requested
model, and provider-reported model recorded by that artifact.

The provider adapters are native implementations behind the same OpsPilot
gateway. Google Gen AI automatic function execution is disabled; Gemini may
only propose one of the same typed functions that the local orchestrator
validates and executes. OpenAI retains its native Responses API adapter.

References:

- [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
