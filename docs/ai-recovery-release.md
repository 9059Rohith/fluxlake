# AI recovery release — 5 November 2026

All four existing free-hosted apps were rebuilt, checked on staged production
deployments, and promoted as the same tested builds. GitHub Actions remains
blocked by the account lock; no passing GitHub Actions run is claimed.

## Actual hosted verification

| Live app | Python tests passed | Explicit optional skips | Runtime source commit |
| --- | ---: | ---: | --- |
| [settlement-recon](https://rohith-settlement-recon.vercel.app/) | 230 | 6 | `96aca344` |
| [fluxlake](https://rohith-fluxlake.vercel.app/) | 226 | 34 | `10e4f84f` |
| [dataguard](https://rohith-dataguard.vercel.app/) | 233 | 1 | `0e1661a5` |
| [pipefoundry](https://rohith-pipefoundry.vercel.app/) | 169 | 23 | `c6d7ec8a` |

The actual Vercel Linux/Python 3.15.1 builders passed **858 tests with
64 skips**, zero failures and zero errors. These are the default release
profiles; PostgreSQL, S3, Spark and container opt-ins retain explicit skip reasons
and their separately dated prior evidence. They are not presented as integrations
executed inside these builds. Local Node UI suites and JavaScript syntax checks
also passed. PipeFoundry's cooldown tests execute its actual form/request logic
against a controlled clock and prove no automatic resubmission.

[Hosted receipt](../evidence/ai-recovery-20261105/hosted-receipt.json) ·
[Build log](../evidence/ai-recovery-20261105/hosted-build.log) ·
[Exact release/alias record](../evidence/ai-recovery-20261105/release.json)

## What changed

The investigation found immediate aborts on transient provider failures in
FluxLake and PipeFoundry; Settlement Recon and DataGuard had only one quick
transient retry. Each adapter now shares at most two retry reservations and six
HTTP sends across an investigation. Backoff increases across turns rather than
resetting for each model call. Existing public visitor/global limits remain in
the database and reserve one visitor attempt before inference.

Transient 500/502/503/504 and applicable network failures can recover. Permanent
client errors and invalid provider protocols remain errors. Long provider
Retry-After delays are propagated without early retries. Settlement Recon,
DataGuard and PipeFoundry parse numeric/date cooldowns without inviting early
resubmission. FluxLake's adapter returns normalized retry seconds to its existing
cooldown UI. No UI automatically replays a question or consumes another visitor
reservation. Logs retain status/type/attempt and allowlisted model/phase where
needed; they exclude keys, provider bodies and prompts.

Scheduling deadlines are 50 seconds in FluxLake and 60 seconds in the other
agents. Per-request socket timeouts are capped by remaining time; late provider
responses are rejected. These are synchronous admission/phase checks, not hard
cancellation of every active read or database tool at an exact wall-clock limit.
Completed tool evidence remains in the conversation rather than being replayed
as a side effect of provider recovery.

## PipeFoundry's free model fallback

The first live PipeFoundry check after the retry release returned HTTP503 after
three actual provider HTTP503 responses. [Sanitized diagnostics](https://github.com/9059Rohith/pipefoundry/blob/main/evidence/ai-recovery-20261105/initial-provider-failure.json)
retain that observation. The logs did not identify the model-call phase, so no
claim is made that those original failures all occurred before tool execution.

The public route now permits a fixed `gemini-3.5-flash-lite` to
`gemini-3.1-flash-lite` switch on the first eligible already-budgeted retry of an
initial 5xx failure, before any assistant/tool response exists. It uses the same
fixed Google endpoint and the existing server-only key in the billing-disabled
free project. A successful response permanently disables switching for that
investigation. Quota faults, long cooldowns, network-only faults and operator
custom-model requests do not trigger the switch. Callers cannot supply a model
or provider override. The actual selected model persists across subsequent
turns and is returned/displayed.

Google documents standard text input/output as free for
[both models](https://ai.google.dev/gemini-api/docs/pricing),
[3.1 function calling](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite),
and [OpenAI-compatible reasoning settings](https://ai.google.dev/gemini-api/docs/openai).
Free eligibility is not a provider availability guarantee. No paid fallback,
independent provider credential, external-search integration or canned answer
was introduced. A deployed last-retry-only version briefly recovered the primary
model after an initial503, then exhausted retries on follow-up503s.
[Phase-aware diagnostics](https://github.com/9059Rohith/pipefoundry/blob/main/evidence/ai-recovery-20261105/last-retry-provider-failure.json)
motivated moving the safe initial switch earlier; no cross-model conversation
reset or additional request budget was introduced.

Final PipeFoundry live model: `gemini-3.5-flash-lite`. Fallback branches passed controlled-fault tests, but live secondary inference was not observed on this request.

## Public retests and remaining limits

All **14 public API checks** passed: database readiness, real retained source
reads, FluxLake replay consistency, PipeFoundry typed manifest review and rejected
anonymous operator mutations. The latest four actual anonymous AI/tool calls returned HTTP200 and provider-generated answers. Initial failed attempts are
preserved alongside the later observations, rather than deleted or relabeled.

[API checks](../evidence/ai-recovery-20261105/public-api.json) ·
[AI calls and prior failure](../evidence/ai-recovery-20261105/public-ai.json)

These observations are not an uptime or universal-answer-quality result.
Public data remains genuine retained source evidence with capture timestamps;
no mock record or fake integration was added. No new browser run is claimed in
this task; native JavaScript tests and actual HTTP/provider paths have their own
explicit scope.

The latest GitHub run still reports the account billing lock before any job
steps begin. [Source-commit run evidence](../evidence/ai-recovery-20261105/github-status.json)
and a [ready-to-use account-resolution/support packet](https://github.com/9059Rohith/settlement-recon/blob/main/docs/github-actions-account-blocker.md)
document the exact blocker. Workflow-write authorization is still unavailable;
prepared hardening patches remain unapplied. No payment, budget or subscription
was changed and no support message was sent.

The Vercel team was freshly verified as active Hobby. Existing Neon deployment
and digest-pinned container profiles were reused. No AWS credentials/profile was
available, no Terraform apply ran and no paid resource was created. This free
hosting alternative establishes actual deployments, not AWS IAM/EKS/RDS operation.
