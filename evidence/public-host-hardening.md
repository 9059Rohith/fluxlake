# Public-host hardening and ephemeral request replay — 2026-10-30

## Executed verification

- **60 passed** on Windows/Python3.12 against actual PostgreSQL16.6: [JUnit](public-hardening-junit.xml).
- **60 passed** inside the Python3.15.1 container against the same real PostgreSQL source: [container JUnit](public-python315-junit.xml). Two visible upstream Starlette/AnyIO test-client deprecation warnings remain in each run.
- Ruff lint/format and runtime dependency consistency pass. Runtime Python audit reports zero known vulnerabilities: [audit](public-dependency-audit.json).
- Fresh Trivy0.76 scan of the final `fluxlake:public` image reports **zero vulnerabilities across all severities and zero secrets**, without ignoring unfixed findings: [full report](public-container-scan.json), [summary](public-container-scan-summary.json). Advisory database UpdatedAt2026-10-30T13:06:28Z; scan completed2026-10-30T14:38:20Z. This is a dated observation, not a promise about future advisories.
- Digest-pinned minimal nonroot image builds and imports PyArrow26.0.0, DuckDB2.0.0 and Psycopg3.3.6 on Python3.15.1. Build tooling is absent from the runtime.
- Actual HTTP smoke used that image as UID10001 with read-only root filesystem, dropped capabilities and an ephemeral noexec `/tmp` tmpfs. It initialized a dedicated empty source with20 real inserts/update/delete, returned exact synthetic INR/USD aggregates, rejected anonymous operational reads401 and fixture writes403, rejected an untrusted Host400, and rebuilt the same projection after a restart that wiped tmpfs. Source remained22 historical events and **zero acknowledged records**: [HTTP/runtime proof](public-runtime-smoke.json).

## Material changes and regressions

Operational reads, metrics, quarantine, OpenAPI and writes require a strong32+byte bearer token. Authentication precedes event parsing. Body/depth/node/string/record/batch bounds and paginated row limits prevent unbounded exposed processing. Persisted attributes are capped per event and across the lake schema. Public mode refuses startup without explicit exact hostnames; security headers and a same-origin CSP apply, with no inline-script exception. No token or source URL enters the public dashboard.

The anonymous view returns only actual SQL aggregates for boolean `synthetic=true` rows; arbitrary attributes/IDs and unmarked records are excluded. Marker strings cannot masquerade as booleans. The real source seeder and explicit bootstrap mark synthetic data honestly.

The request profile uses bounded, repeatable-read **read-only** full-history replay. Tests prove acknowledged rows are reconstructed, late lower-ID commits are caught, source rows remain unacknowledged, oversized history fails before partial publication, source failures reveal no credentials, and an unchanged source does not rewrite snapshots. Reads and pruning share a local lock; request mode retains one current Parquet snapshot. Polling mode retains its original historical-snapshot behavior.

Explicit `FLUXLAKE_SEED_DEMO=true` initialization is a separately coordinated source transaction with a durable once-only marker. Two independent application instances produce the same projection without duplicating seed transactions. Nonempty unmarked sources are refused. This option requires a dedicated empty demo database and migration permissions; unset it and switch to SELECT-only credentials after initialization.

Actual PostgreSQL privilege tests prove the polling relay capability role can SELECT/acknowledge but cannot alter event bodies or delete source transactions. Request replay needs only SELECT. Default development Compose owner credentials remain a local setup convenience, not a public-host privilege recommendation.

## Scope and limits

This is a request-synchronized synthetic demo when `FLUXLAKE_SOURCE_SYNC=request`, not a continuously running streaming worker. Complete unpruned outbox history is mandatory. Replay caps are5000 events,16 MiB total,64 KiB per event, with connection/query timeouts. PostgreSQL is durable; each HTTP instance's lake files are disposable derived state. A static host cannot run it. One API process must own each projection directory. Root provisioning/deployment and live external URLs are verified separately; this local evidence does not claim a hosted deployment or hosted CI pass.

Reproduce container verification with `docker build --target verify -t fluxlake:verify .`, then run that image with `TEST_DATABASE_URL` pointing at a disposable PostgreSQL database and an `/evidence` output mount. Build the final runtime with `docker build -t fluxlake:public .`. See [hosting configuration](../docs/hosting.md) for public environment variables and source-role boundaries.
