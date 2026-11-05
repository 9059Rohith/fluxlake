# Live free-model verification — 5 November 2026

PipeFoundry's backup model is now verified through the actual public HTTPS
application, not just an injected provider response. The normal preferred-model
configuration was restored afterward. The same task also found and mitigated a
DataGuard provider-pool incident and retested all four public applications.

## Real backup inference and automatic recovery

| Observation | Actual result |
| --- | --- |
| Server-pinned backup on the public route | HTTP200, `gemini-3.1-flash-lite`, one real `inspect_github(repository)` tool call, 4,391ms |
| Google response metadata | 2,667 prompt + 110 completion = 2,777 tokens; provider request ID retained |
| Normal configuration restored | Preferred `gemini-3.5-flash-lite`; canonical alias points to its tested deployment |
| Natural primary-model failure | Deployment logs captured HTTP503 on the initial 3.5 attempt |
| Automatic recovery | Same public request completed HTTP200 on 3.1, with a real tool trace, provider request ID and 2,762 tokens |

[Backup response](../evidence/backup-live-20261105/backup-live.json) ·
[Normal-route response](../evidence/backup-live-20261105/primary-live.json) ·
[Routing verification](../evidence/backup-live-20261105/automatic-failover-verification.json) ·
[Sanitized primary-deployment diagnostics](../evidence/backup-live-20261105/primary-routing-diagnostics.json)

The first probe selected 3.1 through the deployment-scoped server setting; no
outage was mocked. The restored normal configuration then encountered a real
primary503 and recovered automatically. The original normal-route probe's exact
35-model predicate therefore reports false even though its HTTP request succeeded:
it received the approved 31 fallback. That raw result is preserved. A separate
routing validation checks the configured preference, real31 response, source
trace, usage, request ID and matching primary-deployment503 diagnostic. It does
not relabel a failed HTTP request as a success.

Both PipeFoundry deployments use source `cded3435` and passed the actual Linux
build gate: **181 Python tests passed, 23 optional integration skips**, with
matching source/test/lock fingerprints. Its 15 Node UI tests also passed. Public
requests still accept only a question, use the fixed repository and approved
provider origin, and share the existing database quotas. Only the server-owned
`PIPEFOUNDRY_PUBLIC_AI_MODEL` can pin an approved model. Invalid values fail before
inference/reservation; operator configuration stays separate. No key was pulled,
decrypted or exposed. Conversation models remain fixed after the first response.

## DataGuard incident and mitigation

The first DataGuard AI retest returned503 after provider503s and a timeout on
follow-up requests. Switching a model in that signed conversation would be
unsafe. Instead, `DATAGUARD_GEMINI_MODEL` now allows exactly the same two approved
free models, and production selects31 from the beginning of each investigation.
The actual public31 request passed in 7,953ms with real capture tools. Invalid
settings fail closed before public quota/provider access; private OpenAI behavior,
public-data-only Gemini tools, retry budget and authentication remain unchanged.
The earlier failure remains in the [complete AI observations](../evidence/backup-live-20261105/public-ai.json).

Google documents standard text input/output as free for
[both approved models](https://ai.google.dev/gemini-api/docs/pricing), including
[3.1 function calling](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite).
Existing server-side keys in billing-disabled projects were reused. No paid
provider, new key, fabricated answer or mock public dataset was introduced.

## Current releases and verification scope

| Live app | Default tests passed | Explicit skips | Runtime source |
| --- | ---: | ---: | --- |
| [settlement-recon](https://rohith-settlement-recon.vercel.app/) | 230 | 6 | `96aca344` |
| [fluxlake](https://rohith-fluxlake.vercel.app/) | 226 | 34 | `10e4f84f` |
| [dataguard](https://rohith-dataguard.vercel.app/) | 244 | 1 | `1c281766` |
| [pipefoundry](https://rohith-pipefoundry.vercel.app/) | 181 | 23 | `cded3435` |

Current default-profile evidence totals **881 passed / 64 skipped**.
The unchanged Settlement/FluxLake profiles retain their earlier same-day run
dates; PipeFoundry and DataGuard have fresh hosted Linux/Python3.15.1 gates.
PipeFoundry's two identical build profiles are counted once, not added twice.
PostgreSQL/S3/Spark/container opt-ins are not misrepresented as executed here.
Their prior integration evidence keeps its original scope and date.

All **14 core public API checks** and the **latest four actual anonymous AI
responses** passed. Checks cover database readiness, genuine retained source
reads, FluxLake replay, typed pipeline review and rejected anonymous operator
mutations. The normal PipeFoundry response correctly uses its backup after the
primary error. [API checks](../evidence/backup-live-20261105/public-api.json) ·
[AI observations](../evidence/backup-live-20261105/public-ai.json) ·
[Current release/alias](../evidence/backup-live-20261105/release.json)

These are observed requests, not an uptime guarantee or proof that every model
answer is correct. Inspect source timestamps and traces. No new browser run is
claimed; UI checks were Node tests and syntax checks. Earlier rendered desktop
and mobile evidence remains separately dated.

## GitHub Actions: remaining account blocker

The freshly observed run for DataGuard source `1c281766` still stops before any
runner step starts: [run42035036519](https://github.com/9059Rohith/dataguard/actions/runs/42035036519).
Its annotation identifies the account billing lock. The connected GitHub identity
differs from the repository owner and has no billing/plan/unlock capability.
Repository push access does not supply that authority; workflow writes also
remain unauthorized. [Capability evidence](../evidence/backup-live-20261105/github-capability-audit.json).

Standard public runners already qualify for free compute. GitHub documents
[owner plan review or Support billing-lock review](https://docs.github.com/en/billing/how-tos/troubleshooting/locked-account)
as appropriate, including failed authorization holds on already-Free accounts.
There is no documented repository switch that removes this account lock. No
payment, downgrade, spending limit, runner registration or support message was
made. The [owner-resolution packet](https://github.com/9059Rohith/settlement-recon/blob/main/docs/github-actions-account-blocker.md)
is ready; **GitHub Actions is not claimed fixed or passing**.

The active Vercel Hobby deployment gates remain the working free hosted CI path.
Existing Neon storage was reused; no paid resource or AWS apply was introduced.
The new model selectors are nonsecret deployment configuration, not public model
overrides or an expansion of operator permissions.
