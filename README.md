# FluxLake

**Real public events → immutable evidence → typed exploration → inspectable analytics.**

[Open workspace](https://rohith-fluxlake.vercel.app) · [Real source API](https://rohith-fluxlake.vercel.app/api/workspace/overview) · [Source documentation](https://docs.github.com/en/rest/activity/events#list-public-events)

FluxLake is a 13-page analytical workspace over real public GitHub events. An operator acquisition fetches up to 100 records from the official fixed-origin REST endpoint, then atomically publishes original JSON, typed silver records, observed schema and a durable run receipt in PostgreSQL. Public exploration never reads private payment CDC tables. The former synthetic public summary is retired with HTTP 410.

## Workflows

| Page | Working capability |
|---|---|
| Overview | Real event/repository/type counts, activity mix, latest receipt and event inspection |
| Sources | Original source URL, acquisition mode, upstream freshness and storage provenance |
| Ingestion | Token-gated GitHub acquisition, bounded publication and source quota receipt |
| Bronze archive | Search, filter, paginate, inspect original JSON and SHA-256 evidence |
| Silver explorer | Search repository/actor/event ID; filter type; export up to 1,000 CSV rows |
| Gold analytics | SQL aggregates by repository, actor or event type; navigate contributing events |
| Schema registry | Observed field types, first/last observation and admission contract |
| Distribution drift | Select retained runs; compare event-type mix with Jensen–Shannon distance |
| Quarantine | Actual rejection reasons, run references and hashes; honest empty state |
| Run history | Success/failure receipts, duplicates, quota, duration and response fingerprints |
| Lineage | Trace event identity through source, acquisition, bronze, silver and gold |
| Lake analyst | Provider-backed read-only tool loop with visible arguments, results and sources |
| Operator access | Verify private bearer token; connect/clear a tab-local session |

## Data and AI boundaries

The GitHub API is a **sample**, not a complete stream. GitHub documents upstream latency from 30 seconds to six hours. Ingestion is operator-triggered. There is no always-on or realtime completeness claim. Duplicate IDs are replay-safe; conflicting content goes to quarantine without overwriting original bronze. Event fingerprints use canonical JSON; run receipts additionally hash exact upstream response bytes.

The analyst supports Google Gemini through its fixed OpenAI-compatible endpoint, using `AI_PROVIDER=gemini`, the server-only `GEMINI_API_KEY`, and model `gemini-3.5-flash-lite`. The selected Google project has billing disabled and uses available free quota. Access still requires the private operator bearer token. Only the operator's public-sample question and selected public GitHub evidence are sent to Gemini; private CDC rows, uploads and credentials are excluded. Do not enter private records or secrets in the question.

The agent selects real read-only overview, bounded search, fixed aggregate and latest-run drift tools, with at most six tool calls across four model turns. Its evidence trace exposes actual tool results and API sources. Gemini's opaque tool-call signatures are preserved only in the provider conversation and never published. Quota errors are explicit HTTP 429 responses with `Retry-After`; at most one short provider retry is attempted. No paid fallback or fabricated response is used. Existing OpenAI configuration remains supported when explicitly selected or when no Gemini key is present.

## Local operation

Requires Python 3.12–3.15 and PostgreSQL. Set your private `DATABASE_URL` and a strong `FLUXLAKE_API_TOKEN` (32–4096 UTF-8 bytes), install the pinned dependencies, then:

```powershell
.venv\Scripts\python -m pip install --no-deps -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps -e .
.venv\Scripts\python scripts/workspace.py migrate
.venv\Scripts\python scripts/workspace.py ingest
.venv\Scripts\fluxlake api --port 18082
```

For cloud environments without direct database access, authenticated `POST /api/workspace/migrate` explicitly initializes the idempotent public schema. Authenticated `POST /api/workspace/ingest` acquires real source events. Public GETs never initialize schemas or fetch upstream data. Exact public hostnames go in `FLUXLAKE_ALLOWED_HOSTS`. Set `FLUXLAKE_SEED_DEMO=false`; the legacy public-demo setting never reenables the retired summary.

## Security and verification

The constant-time bearer boundary, exact-host middleware, CSP without inline scripts/styles, security headers and private CDC authorization remain. New mutations authenticate before bounded body parsing. Source acquisition is fixed to `api.github.com`, rejects redirects, and caps responses at 2 MiB and records at 64 KiB. Public SQL reads are bounded, parameterized and read-only. Aggregate columns use a fixed enum. CSV cells resist spreadsheet formula execution. UI strings and raw JSON are HTML-escaped.

```powershell
.venv\Scripts\python -m pytest -q --junitxml=evidence/workspace-junit.xml
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\python -m pip check
.venv\Scripts\pip-audit --disable-pip --no-deps -r requirements.lock
node --check src/fluxlake/web/workspace.js
```

Recorded PostgreSQL baseline (2026-11-01): **158 passed, zero failures, zero skips**, including the complete PostgreSQL fault/concurrency suite and three public-workspace database integration tests. These ran against a newly created disposable local database on port 55433; production data was never used for destructive tests. The Gemini provider release subsequently passed 134 tests with 30 database tests explicitly skipped while Docker was stopped. Actual hosted Gemini + public database tool + grounded-answer verification is recorded in [Gemini release evidence](docs/gemini-release.md). The pinned dependency audit found no known vulnerabilities. [Current release verification](docs/workspace-release.md) separates real cloud source/database checks from unit/protocol tests. Historical evidence is separately dated.

The public workspace shares the existing isolated application database login with private CDC. Separate read/write principals, managed operator identity/RBAC and scheduled acquisition remain production hardening work. Operator tokens live in tab session storage after explicit connect and should be cleared on shared devices. No payment processing or simulated checkout is added.

## Existing private CDC engine

Authenticated outbox capture, Parquet projection, currency-isolated gold SQL, selected-key inspection and statistical DriftLab remain independent of the public event workspace. Private routes include `/transactions`, `/gold`, `/schema`, `/inspection`, `/drift/compare`, `/events`, `/pipeline`, `/quarantine`, `/metrics` and `/openapi.json`.

See [architecture](docs/architecture.md), [DriftLab](docs/driftlab.md), [hosting](docs/hosting.md), [runbook](docs/runbook.md) and the optional [AWS profile](infra/aws/README.md). Historical synthetic demonstrations and benchmarks are not public-workspace data.
