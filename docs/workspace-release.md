# Public workspace release — 2026-11-01

This release replaces the public synthetic dashboard with 13 connected workflow pages over the official GitHub public-events API. It preserves the separately authenticated private CDC API. The coordinated visual concept uses a slate/teal analytical workspace: dark navigation rail, light surfaces, tables, restrained accents and responsive shared controls.

## Persistence and actual workflows

The fixed source is `https://api.github.com/events?per_page=100`, without a GitHub token, redirects or arbitrary URLs. Dedicated PostgreSQL tables retain runs, bronze JSON/hashes, typed silver, observed field types and quarantine evidence. Explicit operator acquisition atomically publishes all layers behind an advisory lock and poll interval. Psycopg batches writes rather than issuing a network round trip per schema field. Duplicate identity/body replays are idempotent; conflicting bodies never overwrite bronze.

Search, type filters, pagination, CSV export, source evidence modals, run receipts, selected-ID lineage, fixed SQL aggregates and selected-run event-type drift all use this store. Drift describes newly inserted event-type distributions with Jensen–Shannon distance and a 30-event sample gate. It is not a statistical significance or completeness claim. Public GETs never fetch upstream data or write schema. `/demo/summary` always returns HTTP 410.

## AI implementation and blocker

The server implements the real OpenAI Chat Completions function-calling protocol: overview, bounded search, fixed aggregates and latest-run drift. At least one tool is mandatory before accepting an answer. The response includes arguments, actual returned evidence and source API paths. The limit is six tools/four turns, with byte and time budgets. No generated SQL, private CDC access or mutations are available.

No authorized provider key/model exists in production. The status API and UI explicitly show this and authenticated requests return 503. No canned response substitutes for a model. Test-only provider fixtures verify the protocol boundaries, not live provider behavior. Privately configure `FLUXLAKE_AI_KEY` and `FLUXLAKE_AI_MODEL`, redeploy and run a live investigation to enable and verify it.

## Verification

Fresh local suite: **128 passed, 27 skipped**, with two existing deprecation warnings. PostgreSQL integration tests require a dedicated disposable `TEST_DATABASE_URL`. Ruff check/format, JavaScript syntax and dependency compatibility checks passed. The pinned runtime audit found no known vulnerabilities; pins do not include hashes, which pip-audit recommends. Machine-readable evidence: `evidence/workspace-junit.xml`, `evidence/workspace-dependency-audit.json` and `evidence/workspace-live.json`.

Local direct TCP to Neon timed out. Cloud authenticated migration/acquisition and public HTTP checks separately verify actual persistence and source ingestion. These checks do not replace the skipped database fault/concurrency suite. Browser verification uses the built-in IAB with real deployed data, including event evidence and filters; the visual concept was inspected before implementation.

## Material limitations

- GitHub returns an incomplete bounded sample and documents upstream latency of 30 seconds to six hours. No global or realtime activity claim is made.
- Acquisition is manual and authenticated, not scheduled or continuously streaming.
- Public reads and operator writes use the existing isolated PostgreSQL login, not separate database principals.
- Operator access is a shared bearer, not user accounts/RBAC. A connected token lives in tab session storage until cleared/session close.
- AI is implemented but unavailable until credentials/model are configured. Live provider quality, latency and cost are unverified.
- No payment processing or fake checkout is included.
- Hosted CI retains the previously documented account runner restriction. Local tests and deployment are not a hosted CI pass.
