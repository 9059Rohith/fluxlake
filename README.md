# FluxLake

**Real public events → immutable evidence → typed exploration → inspectable analytics.**

[Open workspace](https://rohith-fluxlake.vercel.app) · [Real source API](https://rohith-fluxlake.vercel.app/api/workspace/overview) · [Source documentation](https://docs.github.com/en/rest/activity/events#list-public-events)

FluxLake is a 14-page analytical workspace over real public GitHub events. An operator acquisition fetches up to 100 records from the official fixed-origin REST endpoint, then atomically publishes original JSON, typed silver records, observed schema and a durable run receipt in PostgreSQL. Public exploration never reads private payment CDC tables. The former synthetic public summary is retired with HTTP 410.

The dark observatory interface includes native count/share and distribution charts, a keyboard command palette that searches retained records, sortable explorers, CSV export and an original-evidence drawer. The anonymous analyst formats real answers with inspectable tool evidence. [Design concepts and component system](docs/observatory-design.md) document the visual direction and factual corrections made during implementation; [verification evidence and limits](docs/observatory-verification.md) record the deployed checks.

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
| [Replay audit](https://rohith-fluxlake.vercel.app/workspace/replay) | Reconstruct one/two acquisitions; reconcile hashes, byte counts, exact typed differences and receipts; download fingerprinted evidence |
| Quarantine | Actual rejection reasons, run references and hashes; honest empty state |
| Run history | Success/failure receipts, duplicates, quota, duration and response fingerprints |
| Lineage | Trace event identity through source, acquisition, bronze, silver and gold |
| Lake analyst | Provider-backed read-only tool loop with visible arguments, results and sources |
| Operator access | Verify private bearer token; connect/clear a tab-local session |

[Replay release verification and benchmark](docs/replay-release.md) records the deployed
publication checks, complete PostgreSQL suite and actual retained-source evidence.
The Replay audit also shows a separate offline crash recovery benchmark over 20,000 real
GH Archive events with a reproducible harness and downloadable report.
[Archive recovery benchmark](docs/archive-replay-benchmark.md)

## Data and AI boundaries

The GitHub API is a **sample**, not a complete stream. GitHub documents upstream latency from 30 seconds to six hours. Ingestion is operator-triggered. There is no always-on or realtime completeness claim. Duplicate IDs are replay-safe; conflicting content goes to quarantine without overwriting original bronze. Event fingerprints use canonical JSON; run receipts additionally hash exact upstream response bytes.

Replay audit re-runs the public normalization contract against actual retained JSON in one read-only database snapshot, bounded to two acquisitions, 200 events and 4 MiB. It detects missing silver records, changed normalized fields, identity/provenance differences and mismatched canonical hashes or byte counts. It reconciles publication and rejection counts against durable acquisition receipts. Event time is a presentation order; duplicate bodies, response bodies, source delivery order and database log positions are not retained. Rejected hashes cannot reveal exact changed fields. The separately labeled second pass repeats retained identities only in memory. This does not establish database CDC, stale deliveries, source completeness or exactly-once processing. [Design, research and limits](docs/replay-audit.md).

The analyst supports Google Gemini through its fixed OpenAI-compatible endpoint, using `AI_PROVIDER=gemini`, the server-only `GEMINI_API_KEY`, and model `gemini-3.5-flash-lite`. The selected Google project has billing disabled and uses available free quota. Recruiters can use the public analyst without an account or operator token. Its allowance is 3 attempts per client per 10 minutes, with shared capacity of 2 per minute and 30 per UTC day. The separate operator endpoint and all private operations still require the bearer token. Only the operator's public-sample question and selected public GitHub evidence are sent to Gemini; private CDC rows, uploads and credentials are excluded. Do not enter private records or secrets in the question.

The agent selects real read-only overview, bounded search, fixed aggregate and latest-run drift tools, with at most six tool calls across four model turns. Its evidence trace exposes actual tool results and API sources. Gemini's opaque tool-call signatures are preserved only in the provider conversation and never published. Quota errors are explicit HTTP 429 responses with `Retry-After`; at most one short provider retry is attempted. No paid fallback or fabricated response is used. The public demo is Gemini-only and fails closed before reserving capacity if its Gemini key or provider selection is missing. Existing OpenAI configuration remains supported only by the authenticated operator endpoint.

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

The constant-time bearer boundary, exact-host middleware, CSP without inline scripts/styles, security headers and private CDC authorization remain. Private operations authenticate before bounded body parsing. Public inference uses a separate origin, input and persistent-capacity boundary. Source acquisition is fixed to `api.github.com`, rejects redirects, and caps responses at 2 MiB and records at 64 KiB. Public SQL reads are bounded, parameterized and read-only. Aggregate columns use a fixed enum. CSV cells resist spreadsheet formula execution. UI strings and raw JSON are HTML-escaped.

```powershell
.venv\Scripts\python -m pytest -q --junitxml=evidence/workspace-junit.xml
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\python -m pip check
.venv\Scripts\pip-audit --disable-pip --no-deps -r requirements.lock
node --check src/fluxlake/web/workspace.js
```

Current public-demo verification: **174 passed, zero failures, zero skips**, including the complete PostgreSQL fault/concurrency suite, public-workspace integration tests and persistent rate-limit concurrency checks. Tests used newly created disposable local databases on port 55433 and removed them afterward. Production data was never used for destructive tests. [Public analyst verification](docs/public-analyst-demo.md) distinguishes actual anonymous hosted model/tool/answer checks from controlled local provider tests. The pinned dependency audit found no known vulnerabilities; separately dated earlier verification remains in repository history.

The public workspace shares the existing isolated application database login with private CDC. Separate read/write principals, managed operator identity/RBAC and scheduled acquisition remain production hardening work. Operator tokens live in tab session storage after explicit connect and should be cleared on shared devices. No payment processing or simulated checkout is added.

## Existing private CDC engine

Authenticated outbox capture, Parquet projection, currency-isolated gold SQL, selected-key inspection and statistical DriftLab remain independent of the public event workspace. Private routes include `/transactions`, `/gold`, `/schema`, `/inspection`, `/drift/compare`, `/events`, `/pipeline`, `/quarantine`, `/metrics` and `/openapi.json`.

See [architecture](docs/architecture.md), [DriftLab](docs/driftlab.md), [hosting](docs/hosting.md), [runbook](docs/runbook.md) and the optional [AWS profile](infra/aws/README.md). Historical synthetic demonstrations and benchmarks are not public-workspace data.
