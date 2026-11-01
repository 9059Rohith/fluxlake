# Real Gemini analyst connection — 2026-11-02

The previously unavailable analyst is connected to Google Gemini 3.5 Flash Lite through Google's fixed OpenAI-compatible HTTPS endpoint. The dedicated Google project has billing disabled, and its dedicated API key is restricted to the Generative Language API. Free quota is limited and can change; this is not an unlimited or availability guarantee.

## Actual model and data workflow

An authenticated investigation reached the deployed model, selected `lake_overview` and `aggregate_events`, queried the actual hosted public PostgreSQL event store and produced an answer grounded in those tool results. The retained sample contained 200 real events: 157 PushEvent, 22 CreateEvent, 15 DeleteEvent and 6 PullRequestEvent. The model made two tool calls; the initial observed server investigation took about 2.9 seconds, not a latency guarantee.

Model-visible tool results include their exact trusted `source_api` path alongside observed data, so the model can cite the evidence endpoints. The response exposes tool names, bounded arguments, actual results and source links. Opaque Gemini thought signatures are preserved unchanged when replaying original assistant/tool-call objects to Gemini; they are never included in user-visible traces, logs, screenshots or committed evidence. No generated or fallback answer stands in for an unavailable provider.

## Access, privacy and quota boundaries

- Configuration is server-side: `AI_PROVIDER=gemini`, `GEMINI_API_KEY`, and optional `AI_MODEL` (default `gemini-3.5-flash-lite`). The endpoint is fixed; arbitrary provider URLs are unsupported.
- The actual credential was supplied to encrypted Vercel environment configuration through captured CLI stdin, not a command argument. The private staging file is ignored and excluded from deployments. Browser assets and status responses contain no provider key.
- Investigations still require the existing private operator bearer token. Anonymous requests fail before body parsing; this is not an unrestricted public AI proxy.
- Only the operator's public-sample question and selected public GitHub evidence are sent to Gemini. The tool surface has no private CDC, file-upload, arbitrary SQL, shell or mutation capability. The UI asks operators to exclude secrets and private records from questions.
- At most six tools across four model turns are allowed, with bounded search/results/provider responses and timeouts. Model output is escaped by the existing UI.
- Provider HTTP 429 responses produce an explicit API 429 with a sanitized `Retry-After`. One short retry is permitted when the indicated delay is at most two seconds. Longer waits are returned to the operator rather than blocking or silently changing accounts/providers.
- Existing OpenAI support remains available when selected or when no Gemini key exists. An explicitly selected provider never falls back to another configured account after an error.

## Verification and limits

The current complete local run passed **134 tests with 30 PostgreSQL tests explicitly skipped**, plus two existing deprecation warnings. Docker was stopped for this provider-only change; the preceding full PostgreSQL baseline passed **158 tests with no skips** and remains separately recorded. There are no new database queries or schema changes in this provider release. All 27 focused workspace/provider tests passed after the exact-source improvement. Ruff, formatting, JavaScript syntax and installed dependency compatibility checks passed.

Provider tests cover fixed endpoint selection, explicit account boundaries, key redaction, opaque signature round trips, bounded quota retry and authenticated API retry headers. Actual hosted model + database tool + final answer evidence is recorded separately in `evidence/gemini-live.json`; it is not a test double. The free tier has no billing-backed fallback. Operator identity remains the existing shared bearer model rather than per-user RBAC.

Official integration reference: [Google Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai).
