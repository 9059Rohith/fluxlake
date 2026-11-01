# Public workspace release — 2026-11-01

The initial AI credential limitation below was superseded by the [Gemini connection on 2026-11-02](gemini-release.md). The historical verification remains dated here.

This release replaces the public synthetic dashboard with 13 connected workflow pages over the official GitHub public-events API. It preserves the separately authenticated private CDC API. The coordinated visual concept uses a slate/teal analytical workspace: dark navigation rail, light surfaces, tables, restrained accents and responsive shared controls.

## Persistence and actual workflows

The fixed source is `https://api.github.com/events?per_page=100`, without a GitHub token, redirects or arbitrary URLs. Dedicated PostgreSQL tables retain runs, bronze JSON/hashes, typed silver, observed field types and quarantine evidence. Explicit operator acquisition atomically publishes all layers behind an advisory lock and poll interval. Psycopg batches writes rather than issuing a network round trip per schema field. Duplicate identity/body replays are idempotent; conflicting bodies never overwrite bronze.

Search, type filters, pagination, CSV export, source evidence modals, run receipts, selected-ID lineage, fixed SQL aggregates and selected-run event-type drift all use this store. Drift describes newly inserted event-type distributions with Jensen–Shannon distance and a 30-event sample gate. It is not a statistical significance or completeness claim. Public GETs never fetch upstream data or write schema. `/demo/summary` always returns HTTP 410.

## AI implementation and blocker

The server implements the real OpenAI Chat Completions function-calling protocol: overview, bounded search, fixed aggregates and latest-run drift. At least one tool is mandatory before accepting an answer. The response includes arguments, actual returned evidence and source API paths. The limit is six tools/four turns, with byte and time budgets. No generated SQL, private CDC access or mutations are available.

No authorized provider key/model exists in production. The status API and UI explicitly show this and authenticated requests return 503. No canned response substitutes for a model. Test-only provider fixtures verify the protocol boundaries, not live provider behavior. Privately configure `FLUXLAKE_AI_KEY` and `FLUXLAKE_AI_MODEL`, redeploy and run a live investigation to enable and verify it.

## Verification

Final local suite: **158 passed, zero failed, zero skipped** in 54.45 seconds, with two existing deprecation warnings. Tests used a newly created dedicated disposable PostgreSQL database on local port 55433; it was removed afterward. Production PostgreSQL was never used for destructive tests. The suite includes all existing database fault/concurrency checks plus three new public-workspace integration tests for atomic publication, deduplication and conflicting-content quarantine, durable source failures, drift comparisons, filtered HTTP reads and CSV export. PostgreSQL integration tests require a dedicated disposable `TEST_DATABASE_URL`. Ruff check/format, JavaScript syntax and dependency compatibility checks passed. The pinned runtime audit found no known vulnerabilities; pins do not include hashes, which pip-audit recommends. Machine-readable evidence: `evidence/workspace-junit.xml`, `evidence/workspace-postgres-junit.xml`, `evidence/workspace-dependency-audit.json` and `evidence/workspace-live.json`.

Local direct TCP to Neon timed out. Cloud authenticated migration/acquisition and public HTTP checks separately verify actual persistence and source ingestion. The database fault/concurrency suite was subsequently verified against local PostgreSQL with no skips. Browser verification uses the built-in IAB with real deployed data, including event evidence and filters; the visual concept was inspected before implementation.

## Material limitations

- GitHub returns an incomplete bounded sample and documents upstream latency of 30 seconds to six hours. No global or realtime activity claim is made.
- Acquisition is manual and authenticated, not scheduled or continuously streaming.
- Public reads and operator writes use the existing isolated PostgreSQL login, not separate database principals.
- Operator access is a shared bearer, not user accounts/RBAC. A connected token lives in tab session storage until cleared/session close.
- AI is implemented but unavailable until credentials/model are configured. Live provider quality, latency and cost are unverified.
- No payment processing or fake checkout is included.
- Hosted CI retains the previously documented account runner restriction. Local tests and deployment are not a hosted CI pass.

## Verified deployed result

Final application build: commit `cf6decd`, Vercel deployment `dpl_CnxdAs1qUYTSLFyFdpxtwURHWuFF`, production aliases [rohith-fluxlake.vercel.app](https://rohith-fluxlake.vercel.app) and [fluxlake.vercel.app](https://fluxlake.vercel.app).

The final deployment retained **200 actual GitHub events across 198 repositories**, acquired in two successful 100-event runs. Both raw response fingerprints are stored. The second batched acquisition took 752 ms in the server's measured acquisition/publication section (not a latency guarantee). Two-run drift returned a descriptive distance of about 0.0535 bits, with actual baseline/candidate cells verified in the browser.

**40 final live HTTP checks passed**: all 13 pages, source/bronze/silver/gold/schema/quarantine/run/drift reads, filtered search, type filters, raw JSON canonical hash, 200-row CSV export, legacy private-route authorization, anonymous mutation rejection before parsing, retired synthetic summary (410), valid private pipeline read (200), and actual missing-provider AI response (503). Persistence was observed after multiple independent container deployments.

The built-in browser verified actual populated overview, repository filtering, original event evidence, reversed run selections, zero console warnings/errors and responsive desktop/mobile behavior. A mobile navigation closing defect was found and repaired; the final deployed sidebar closes and is removed from the accessibility tree when hidden. Screenshots and a browser verification ledger are committed under `evidence/workspace-*`.
