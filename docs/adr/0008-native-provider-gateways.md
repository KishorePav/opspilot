# ADR 0008: Keep orchestration local and add native provider gateways

- Status: accepted
- Date: 2026-08-02

## Context

The investigator protocol and orchestrator were provider-independent, but the
first live harness implemented only OpenAI's Responses API. Entering a Gemini
model name into that workflow still routed the request to OpenAI, producing a
fast provider rejection with no model output. The user also requires a
zero-spend path for the first live baseline.

## Decision

Add a native Google Gen AI adapter beside the native OpenAI adapter. Keep all
scope, evidence, citation, duplicate-call, and budget enforcement in the local
orchestrator. Provider adapters may translate tool declarations, model calls,
function results, and usage metadata only.

Require an explicit provider in the live runner and reject provider/model
mismatches before constructing a client. The protected workflow defaults to
Gemini 3.6 Flash and the `GEMINI_API_KEY`; OpenAI remains an explicit optional
path. Gemini automatic function execution is disabled, function-call mode is
forced, output and cumulative token budgets remain active, and SDK retries are
limited to the initial attempt.

When a provider fails, retain only a bounded provider name, exception type,
stable error code, HTTP status, and request ID. Never write raw exception text,
request bodies, prompts, evidence contents, or credentials into artifacts.

## Consequences

- OpsPilot is provider-neutral in both architecture and live implementation.
- A model switch cannot silently route to the wrong provider.
- The free-tier Gemini path can establish a live baseline without adding
  OpenAI API billing.
- Provider SDKs and schema dialects require separate adapter tests.
- A free-tier account may use submitted synthetic data for provider product
  improvement; real employer or customer incidents remain prohibited.
- A successful live quality claim still requires a passing protected artifact.

## References

- [Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
