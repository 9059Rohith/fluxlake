# Verification evidence â€” 2026-10-30

This evidence distinguishes executed local checks from supplied managed-cloud code. Commands ran on Windows 11 with Python 3.12.0, Docker Desktop Linux Engine, and Terraform 1.13.5. No AWS resources were provisioned by this repository build.

## Executed checks

| Check | Command / scope | Observed result |
|---|---|---|
| Full correctness and API suite | `.venv/Scripts/python -m pytest -q --tb=short --junitxml=evidence/junit.xml`, `TEST_DATABASE_URL` set to dedicated PostgreSQL 16.6 `fluxlake_test` DB on port 55433 | **39 passed**, two upstream test-client deprecation warnings |
| Lint | `.venv/Scripts/ruff check .` | All checks passed |
| Format | `.venv/Scripts/ruff format --check .` | 14 files already formatted |
| Dependency consistency | `.venv/Scripts/python -m pip check` | No broken requirements found |
| Runtime dependency vulnerability audit | `.venv/Scripts/pip-audit --disable-pip --no-deps -r requirements.lock -f json -o evidence/dependency-audit.json` | **21 packages, zero known vulnerabilities** at check time |
| Python compilation | `python -m compileall -q src scripts infra/aws/glue_job.py` | Exit 0; verifies syntax, not Glue runtime behavior |
| Compose configuration | `docker compose config --quiet`, local env values configured | Exit 0 |
| Terraform format | `terraform -chdir=infra/aws fmt -check` | Exit 0 |
| Terraform initialization | Verified local provider mirror after direct registry download stalled | AWS provider **6.71.0** installed; official release ZIP hashes recorded, including Linux |
| Terraform provider-schema validation | `terraform -chdir=infra/aws validate -no-color` | **Success! The configuration is valid.** |
| Container build | `docker build -t fluxlake:0.1.0 . --progress=plain` | **Exit 0**, final patched image built successfully |
| Compose acceptance test | `python scripts/smoke.py` | **Passed**: automatic insert/update/delete, gold reconciliation, auth/Unicode edge cases and container restart |

Raw artifacts: [JUnit](junit.xml), [dependency audit](dependency-audit.json), [Terraform validation](terraform-validate.txt), [Terraform version](terraform-version.json), [official provider archive checksums](terraform-provider-aws-6.71.0-SHA256SUMS.txt), [Compose HTTP acceptance](compose-smoke.json), [runtime container configuration](container.json).

## What the tests prove

Real PyArrow writes/reads typed Parquet, and DuckDB computes literal expected currency aggregates. Tests cover inserts, updates, deletes, duplicate delivery, stale delivery, tombstone resurrection prevention, ID/version collisions, malformed contracts, additive attributes, type drift, concurrent local writers, immutable-archive corruption detection, previous snapshot preservation, and recovery after SQLite commit before snapshot publication.

Actual PostgreSQL tests cover rollback removing an outbox record, insert/update/delete revisions, source replay after restart, delete/reinsert version continuity, a lower identity value committing after a higher one was consumed, sink publication failure keeping source rows unacknowledged, reserved source attribute rejection, and CLI initialization from an explicit SQL file. API tests cover missing/wrong/correct bearer token behavior, disabled writes when no token exists, body/batch bounds, quarantine authorization, readiness, gold reads, metrics, and non-finite JSON rejection, non-ASCII authorization rejection, and whitespace-only disabled configuration. Review regressions prove invalid UTF-8 strings cannot poison committed state/restart; valid multibyte strings round-trip. Directory-sync fault tests prove bronze failure prevents state commit and silver failure preserves the previous manifest until replay recovery.

The two warnings come from upstream Starlette's transition from `httpx` to `httpx2` and its AnyIO BlockingPortal alias; they are not hidden by filters. No integration tests are skipped in the recorded full run. Test-first and regression failures are described in [test-first.md](test-first.md).

## Measured performance

Nearest-rank quantiles of real durable sink **batch** return latency; first ten warmup events excluded. Files include all raw samples and exact relevant dependency versions.

| Workload | p50 | p95 | p99 | Events/second |
|---|---:|---:|---:|---:|
| 200 events in 200 batches of 1 | 94.7 ms | 236.3 ms | 375.1 ms | 8.34 |
| 1000 events in 100 batches of 10 | 192.0 ms | 365.9 ms | 465.6 ms | 45.83 |

See [benchmark.json](benchmark.json) and [benchmark-batched.json](benchmark-batched.json). This deliberately includes bronze fsync, SQLite commit and full Parquet snapshot publication. It excludes PostgreSQL polling, network transport and all AWS services. It is a local filesystem demonstration, not a production SLO or managed-service capacity claim.

## Not executed / limits

- No AWS credentials were available to the coordinating build. DMS endpoint connectivity, source WAL capture, Kinesis delivery, managed Glue/Iceberg execution and Athena visibility have **not** been exercised in a live account. Terraform validation proves syntax/provider schema, not deployment success. The actual PySpark job is supplied and syntax-checked.
- Hosted GitHub Actions jobs could not start because of an account-level runner restriction. The workflow is supplied; no hosted pass is claimed. Publication and hosted-run evidence are managed separately by the coordinating task.
- Process interruption/recovery is tested; hardware power-loss and disk-controller guarantees are environment-dependent. POSIX parent directories are now fsynced for new directories, bronze objects, Parquet targets and manifest replacements; fault tests verify commit/publication ordering. Windows uses file fsync plus atomic rename and retains the documented process-crash scope. Off-host backups remain necessary.
- The local profile serializes writers and rewrites all live rows per batch. It is intentionally single-node, with unbounded retained history until an explicit retention policy is applied. It does not give atomic visibility across a whole source transaction spanning multiple relay batches.
- The audit covers locked Python runtime packages, not the base OS image, PostgreSQL image, Python interpreter or AWS-managed runtime. The development PostgreSQL image must receive normal patch/security review before production use.
- Read endpoints are loopback-only and unauthenticated by design; authenticate all sensitive ingress before exposing it beyond the development host.

## Publication and additional image check

Complete source and both workflows are published at https://github.com/9059Rohith/fluxlake; the local and remote trees were compared. A separate Trivy image scan of the running fluxlake:0.1.0 image found **0 fixable HIGH/CRITICAL findings**, using a read-only cached advisory database updated **2026-10-20**. Reports: container-scan.json and container-scan-summary.txt. This is a dated image check, not assurance against newer advisories; the current Python dependency audit above remains separate.
