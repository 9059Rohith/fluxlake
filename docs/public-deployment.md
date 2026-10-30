# Verified public deployment

[Open FluxLake](https://rohith-fluxlake.vercel.app) · [Public summary API](https://rohith-fluxlake.vercel.app/demo/summary) · [Machine-readable release evidence](../evidence/public-release-verification.json)

The coordinating release task verified the live HTTPS service on 2026-10-30, including a browser-rendered dashboard. This is a real source-backed synthetic demonstration: PostgreSQL stores the transactions and retained outbox; Python replays that history into Parquet and DuckDB computes the displayed aggregates. It is not a static page or an always-on streaming-worker claim.

## Deployed free-tier profile

| Component | Verified configuration |
|---|---|
| HTTP compute | Vercel Hobby Docker/OCI container function |
| Durable source | Neon Free PostgreSQL, with complete retained outbox history |
| Application profile | `FLUXLAKE_SOURCE_SYNC=request` |
| Public view | `FLUXLAKE_PUBLIC_DEMO=true`; boolean synthetic markers only |
| Host allowlist | `rohith-fluxlake.vercel.app`, `localhost`, `127.0.0.1` |
| HTTP port | `PORT=8000` |
| Derived state | `FLUXLAKE_ROOT=/tmp`; disposable per-instance SQLite/bronze/Parquet |
| Bootstrap | Explicit once-only synthetic source initialization, with a durable PostgreSQL marker |
| Source activity | 20 real synthetic inserts, one update and one delete; 22 retained outbox events, 19 current rows, no replay acknowledgements |

The tiers are usage-limited and instances may idle or restart. Readiness/data requests reconstruct a bounded projection from durable PostgreSQL; successful source refreshes cache for five seconds. No local file is treated as durable cloud storage. Replay reads every retained record, including previously acknowledged ones, without a maximum-ID checkpoint or cross-instance acknowledgement race. Complete unpruned history remains mandatory. See [hosting.md](hosting.md) for the 5000-event/16 MiB limits, readiness behavior and operator configuration.

## Database and HTTP boundaries

The hosted source uses a separate isolated non-superuser SQL identity. Cross-project database CONNECT was verified denied; credentials are not shared publicly or embedded in browser code. Connection settings enforce hostname verification with `sslmode=verify-full`, the trusted CA file `/etc/ssl/certs/ca-certificates.crt`, and `channel_binding=require`. Database URLs and administrative token values remain private.

The SQL role has server defaults of **15 seconds statement timeout**, **10 seconds lock timeout**, and **30 seconds idle-in-transaction timeout**. Application replay and optional bootstrap apply stricter **5-second connection/statement limits** and a **2-second lock limit**. The server defaults and application overrides are separate controls.

Operational replay uses repeatable-read, read-only transactions and never updates source acknowledgements. Explicit bootstrap needs schema/business-write privileges only for a dedicated empty synthetic source; the general hosting guide recommends disabling bootstrap and using SELECT-only credentials afterward. The deployed identity is documented as isolated/non-superuser, rather than incorrectly described as necessarily SELECT-only while bootstrap is enabled.

Live checks observed:

- `/health`, `/ready` and `/demo/summary`: **200**.
- Anonymous `/metrics`, `/transactions`, `/pipeline`, `/openapi.json` and mutations: **401**.
- An operational read with the private administrative token: **200**.
- `/events` with valid administrative credentials in request-sync mode: **403**; instance-local fixture writes remain disabled.
- No administrative token is public. Public output includes only synthetic currency aggregates, not transaction IDs or arbitrary attributes.

The verified summary contains INR: **10 transactions /126250 minor units**, and USD: **9 transactions /102375 minor units**. Currencies are never summed together. This is synthetic demonstration data, not customer traffic.

## Measured public request latency

The release evidence records **12 sequential warm public HTTPS requests from India**, using nearest-rank quantiles:

| p50 | p95 | p99 |
|---:|---:|---:|
| 515.939 ms | 823.604 ms | 823.604 ms |

This is a small warm-request observation, not a load test, cold-start measurement or production latency guarantee. With 12 samples, both reported tail quantiles select the maximum observed sample. The historical local durable-sink benchmark is a different workload and is not compared as an equivalent end-to-end measurement.

GitHub Actions remains subject to its separately documented account-level runner restriction; successful public deployment and local verification do not imply a hosted CI pass. The optional AWS DMS/Kinesis/Glue/Iceberg/Athena infrastructure remains a separate managed profile, not the stack behind this public service.
