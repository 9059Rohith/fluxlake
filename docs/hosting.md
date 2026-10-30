# Public hosting and request-synchronized projections

## Supported profiles

| Profile | Compute/state requirements | Source semantics |
|---|---|---|
| `FLUXLAKE_SOURCE_SYNC=poll` (default) | Long-running `fluxlake worker` plus API sharing one durable `/data` volume | Exact-row source acknowledgements after durable sink publication; near-real-time polling |
| `FLUXLAKE_SOURCE_SYNC=request` | HTTP container instances with their own reconstructable ephemeral `/data`; durable external PostgreSQL | Read-only full-history replay on requests, cached five seconds; never acknowledges source records |

The request profile is suitable for bounded synthetic demonstrations on autoscaling or idle-expiring HTTP containers. It does **not** claim a continuously running worker or continuous CDC freshness. The dashboard labels request-triggered source replay explicitly. API construction and `/health` do not connect to PostgreSQL or wait for a global lock. The first readiness/data request performs reconstruction; `/ready` and public data return 503 until successful replay, and fail closed on source outages or capacity limits. Within an instance, refreshes serialize and successful results cache for five seconds. Failed connection attempts also back off for five seconds.

Each request-profile replica has independent SQLite/bronze/Parquet files. It reads **all** retained outbox rows, including `processed_at` records, from a PostgreSQL repeatable-read, read-only transaction. There is no maximum-ID checkpoint, so a lower-ID transaction committing late is included on the next replay. Existing relay acknowledgements do not hide history. Independent replicas never acknowledge records, so they need no exclusive PostgreSQL worker fence and do not freeze each other's startup.

The bounded profile admits at most 5000 historical outbox records, 16 MiB of canonical event data in a replay, and 64 KiB per event. The application uses five-second connection/statement timeouts and a two-second lock timeout. In the verified hosted deployment, the isolated SQL role also has server defaults of 15s statement_timeout, 10s lock_timeout and 30s idle_in_transaction_session_timeout; the application overrides are stricter. It collects/checks the full bounded snapshot before publication. An over-limit source returns 503; it is not silently truncated. Beyond those limits, use durable shared storage or a managed lakehouse rather than disguising a larger deployment as a free demo.

**Complete retained history is mandatory.** Do not prune outbox events, reset its revision ledger, truncate business tables, or mutate event bodies. Tombstone and update history must survive. A source reset or history migration requires coordinated cache replacement/rebootstrap. The default schema never automatically prunes history. PostgreSQL is the durable system of record in this profile; local files are disposable derived projections. Static-only hosts cannot execute either profile.

## Public exposure configuration

Set these as private hosting environment variables (never browser JavaScript or repository files):

- `FLUXLAKE_PUBLIC_DEMO=true`
- `FLUXLAKE_ALLOWED_HOSTS=your-exact-public-hostname` (no scheme, port or wildcard). Public mode refuses startup without explicit exact hostnames. Local loopback health hosts remain allowed.
- `FLUXLAKE_API_TOKEN`: a random ASCII token of at least 32 characters.
- `FLUXLAKE_SOURCE_SYNC=request` for ephemeral HTTP instances, or `poll` for a durable long-running worker deployment.
- `DATABASE_URL`: the private TLS-enabled PostgreSQL connection URL for request replay. Use `sslmode=verify-full` with an appropriate trusted CA where supported.
- `PORT`: hosting-assigned HTTP port; default container port is 8080.
- `FLUXLAKE_ROOT=/data`: writable per-instance directory.
- `FORWARDED_ALLOW_IPS`: only the actual trusted ingress proxy addresses. Do not trust arbitrary clients' forwarded headers. Terminate TLS and enforce ingress request/rate limits at the host.

Public routes are `/`, fixed dashboard assets, minimal `/health` and `/ready`, and `/demo/summary`. The demo summary contains currency aggregates only for rows whose `data.synthetic` marker is the boolean `true`. Unknown or unmarked records, row IDs and arbitrary attributes never enter that public response. Missing markers are not silently reclassified as synthetic. Run `scripts/seed.py` against the **real source PostgreSQL** to commit synthetic inserts, an update and a delete; the seeder marks those records explicitly. The dashboard reads actual Parquet/SQL results, not embedded fixture totals.

All operational reads, metrics, schema, quarantine, OpenAPI and `/events` require bearer authorization. `/events` is disabled with 403 in request-sync mode because instance-only fixture writes would diverge from durable source history. Perform business writes through the private source, then allow a request to replay them. No administrator token is embedded in the dashboard.

## Database privileges and lifecycle

Apply `sql/source.sql` with a migration identity before starting either profile. `sql/relay-role.sql` creates a NOLOGIN capability role granting only outbox SELECT and processed_at UPDATE; grant it to a separately provisioned private relay login. Actual PostgreSQL tests verify it can acknowledge rows but cannot mutate event bodies or delete business transactions. A request-only replay identity needs **SELECT only** on the outbox and schema USAGE. The public API requires no migration, source-write or role-administration credentials. Keep a separate private owner/business writer for initialization and synthetic seeding.

A single long-running acknowledged relay still needs its shared durable sink volume. Do not point multiple independent ephemeral acknowledged relays at the same global `processed_at` checkpoint. The read-only request profile deliberately avoids that problem; it is not implemented by resetting acknowledgement flags.

The [verified public Vercel Hobby / Neon Free deployment](public-deployment.md) and its live checks are documented separately. Application configuration does not create provider accounts; platform provisioning and deployment are distinct from replay logic.

### Explicit source bootstrap and bounded local cache

`FLUXLAKE_SEED_DEMO=true` is an explicit operator opt-in for a dedicated empty PostgreSQL database. On the first source request it applies the packaged source schema, commits 20 synthetic inserts/update/delete and a durable once-only marker in one transaction. A transaction advisory lock prevents duplicate seeding by simultaneous cold instances. This short initialization coordination is separate from normal replay; HTTP construction/health never waits for it. Nonempty unmarked sources or retained histories are refused without seeding. Bootstrap needs a migration/business-writer identity; once initialized unset the flag and use SELECT-only credentials for replay. No generated activity is presented as customer traffic.

Request-mode cache retention differs from polling mode: an unchanged full-history fingerprint skips republishing, and changed projections retain one current Parquet snapshot. Reads and pruning share the per-instance lock so cleanup cannot unlink a file being queried. Bronze remains content-addressed; the 16 MiB complete-history bound and schema/string/event limits cap this derived demo cache. Use one API process per projection directory. Default polling mode retains historical snapshots as before.
