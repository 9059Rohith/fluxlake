# FluxLake

A near-real-time transaction lakehouse you can run and break locally. PostgreSQL commits each transaction change and its outbox record atomically. A Python worker delivers those records at least once; the sink keeps one correctly ordered result, immutable bronze evidence, real Parquet silver snapshots, and currency-safe gold SQL aggregates.

**Local: transactional outbox polling, not WAL capture.** The optional AWS profile performs actual DMS WAL capture of the outbox into Kinesis and a Glue PySpark Iceberg `MERGE`. Managed infrastructure is supplied as deployable code; see [verification evidence](evidence/verification.md) for exactly what has run. No cloud deployment or production throughput is implied.

```mermaid
flowchart LR
  A[PostgreSQL transactions] -->|same SQL transaction / trigger| B[Outbox + per-key revision]
  B -->|SKIP LOCKED / exact-row ack| C[Python relay]
  C --> D[Bronze content-addressed JSON]
  C --> E[SQLite receipts + tombstones]
  E --> F[Atomic Parquet snapshot + manifest]
  F --> G[DuckDB gold SQL]
  G --> H[FastAPI dashboard / metrics]
  B -. WAL / DMS managed alternative .-> K[Kinesis]
  K --> L[Glue PySpark]
  L --> M[S3 bronze + Iceberg silver]
  M --> N[Athena]
```

## Run locally

Requirements: Python 3.12 and Docker Engine / Docker Compose. Commands below use PowerShell; equivalent shell environment variables work on Linux.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --no-deps -r requirements-dev.lock
.venv\Scripts\python -m pip install --no-deps -e .
$env:POSTGRES_PASSWORD = [guid]::NewGuid().ToString('N')
$env:FLUXLAKE_API_TOKEN = [guid]::NewGuid().ToString('N')
# Persist these values in an ignored .env if you need to reuse the same DB volume.
docker compose up -d --build
$env:DATABASE_URL = "postgresql://fluxlake:$($env:POSTGRES_PASSWORD)@127.0.0.1:55433/fluxlake"
.venv\Scripts\python scripts/seed.py
Start-Process 'http://localhost:18082'
Invoke-RestMethod http://localhost:18082/gold
```

Source writes go to PostgreSQL. `/events` is an authenticated fixture/replay route; use an isolated lake root when replaying arbitrary inputs. `/docs` describes the API. Read endpoints are intentionally accessible on loopback in the development profile. Production ingress must authenticate all sensitive reads and terminate TLS.

Run the worker and API directly when Docker builds are unavailable:

```powershell
# PostgreSQL still runs in Compose; worker and API share the same --root.
docker compose up -d postgres
.venv\Scripts\fluxlake worker --root data
# In another terminal, with FLUXLAKE_API_TOKEN set:
.venv\Scripts\fluxlake api --root data --port 18082
```

To test with PostgreSQL:

```powershell
docker compose exec postgres createdb -U fluxlake fluxlake_test
$env:TEST_DATABASE_URL = "postgresql://fluxlake:$($env:POSTGRES_PASSWORD)@127.0.0.1:55433/fluxlake_test"
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\pip-audit --disable-pip --no-deps -r requirements.lock
.venv\Scripts\python scripts/benchmark.py --events 200
```

Without `TEST_DATABASE_URL`, the database integration tests explicitly skip. [The reproducible benchmark](evidence/benchmark.json) reports measured durable sink latency and raw samples, with no simulated cloud claims. Batch size controls snapshot rewrite cost.

## Contract and guarantees

An event contains `event_id`, `key`, positive integer `version`, `op` (`insert`, `update`, `delete`), timezone-aware `occurred_at`, and `data`. Live data requires nonnegative integer `amount_minor`, uppercase three-letter `currency`, and `status` (`pending`, `settled`, `failed`). All JSON strings must encode as strict UTF-8; unpaired surrogate escapes quarantine before state commit. Extra safe scalar attributes evolve the registry and appear as nullable typed Parquet columns; changing an existing attribute type goes to quarantine. Money is never summed across currencies.

- Same event ID and body → duplicate, no state mutation.
- Same event ID with a different body, or equal key/version with a different event → quarantine.
- Older revision → durably record as stale, preserve newer state.
- Delete → retain a durable tombstone so old inserts cannot resurrect the row.
- Crash after state commit → reconstruct Parquet on restart. Crash before PostgreSQL ack → replay; receipts avoid double application.
- Every accepted JSON input is preserved in content-addressed bronze, including quarantined and stale events. Exact replay reuses the same object. This is a raw event archive, not a per-delivery audit log.
- Source queue checkpoint is each outbox row's `processed_at`; sequence IDs are not assumed to be commit order.

SQLite state/receipts plus bronze and Parquet live on the same durable volume. This is a single-node correctness-oriented profile with serialized writers and full snapshot rewrites per batch. It does not provide multi-host consensus, cross-key transactional visibility, or infinite-scale streaming. See [architecture](docs/architecture.md), [decisions](docs/adr.md), [security](SECURITY.md), [operations](docs/runbook.md), [AWS deployment](infra/aws/README.md), and [interview guide](docs/interview.md).

## Project map

| Area | Implementation |
|---|---|
| Durable sink | `src/fluxlake/lake.py` |
| PostgreSQL source and relay | `sql/source.sql`, `src/fluxlake/worker.py` |
| API, freshness, dashboard, metrics | `src/fluxlake/api.py` |
| AWS managed deployment | `infra/aws/main.tf`, `infra/aws/glue_job.py` |
| Correctness and integration tests | `tests/` |
| Benchmarks, verification, traceability | `evidence/`, `docs/requirements.md` |

CI runs tests with PostgreSQL, lint/format, dependency audit, Docker build, and Terraform validation. An optional manual OIDC workflow generates a cloud plan; it never applies infrastructure automatically.


## Measured local performance

On the recorded Windows/Python 3.12 host with patched dependencies, the committed benchmark results are:

| Workload | Measured batches | p50 / p95 / p99 batch latency | Throughput |
|---|---:|---:|---:|
| 200 events, batch size 1 | 200 | 95 / 236 / 375 ms | 8.34 events/s |
| 1000 events, batch size 10 | 100 | 192 / 366 / 466 ms | 45.83 events/s |

These are durable local sink timings, including raw-file fsync, SQLite commit and a complete Parquet snapshot publication. They exclude PostgreSQL polling, network and AWS. The batch p99 is not per-event latency. Raw timings and dependency versions are in [single-event evidence](evidence/benchmark.json) and [batched evidence](evidence/benchmark-batched.json). Reproduce the second workload with `python scripts/benchmark.py --events 1000 --batch-size 10 --output evidence/benchmark-batched.json`.
