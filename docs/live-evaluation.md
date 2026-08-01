# Controlled live-model evaluation

The live harness measures the existing bounded investigator against versioned
synthetic incidents. It is deliberately separate from deterministic CI and the
public demo.

## Invocation controls

The runner exits before constructing a provider client unless all of these are
true:

- `--confirm-live-api` is present;
- `OPENAI_API_KEY` exists in the runtime environment;
- the model name passes a conservative character allowlist;
- `--max-cases` is between one and ten;
- each dataset case has validated round, tool, evidence, and total-token caps.

The default command evaluates one case. Each provider call has a 30-second
timeout, a 4,096-output-token limit, low reasoning effort, and no SDK retries.
The orchestrator stops further progress when cumulative reported usage exceeds
the case token budget. A completed call may cross that fence, but no subsequent
tool or model call is allowed.

```bash
OPENAI_API_KEY='runtime-only' python scripts/run_live_agent_eval.py \
  --confirm-live-api \
  --model gpt-5.6 \
  --max-cases 1
```

## Artifact contract

`artifacts/evaluations/live-agent-eval.json` records:

- UTC generation time and total duration;
- requested model and provider-reported model identifiers;
- SHA-256 of the complete JSONL dataset and selected case IDs;
- structured report, evidence ledger, tool trace, grader details, and failure
  taxonomy when applicable;
- input, cached input, output, reasoning, and total tokens;
- estimated cost only when the caller supplied a model-matched version label
  and all three rates.

Artifacts contain only repository-owned synthetic data. A run should still be
reviewed before it is attached to a release or portfolio claim.

## GitHub workflow

The `Controlled live-model evaluation` workflow is manual only. Configure a
GitHub environment named `live-evaluation`, require a reviewer, and store
`OPENAI_API_KEY` as an environment secret. The job has read-only repository
permissions, evaluates one case by default, and uploads the JSON artifact even
when a grader threshold fails after the artifact was written.

Never add the live workflow to pull-request or `push` triggers. A successful
run establishes quality only for the selected dataset bytes, commit, requested
model, and provider-reported model recorded by that artifact.

The design follows OpenAI's current guidance to inspect tool-level traces while
debugging and promote representative behavior into repeatable datasets and
evaluation runs:

- [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals)
- [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
