# Requirements traceability

| Requirement | Implementation | Evidence |
|---|---|---|
| Transaction capture | PostgreSQL AFTER trigger + outbox revision ledger | actual PostgreSQL rollback/commit integration test |
| Insert/update/delete | Lake.apply versioned after images and tombstones | test_insert_update_delete_stale_and_duplicate |
| Replay/idempotence | Atomic SQLite receipts with body hashes | duplicate/collision/restart tests |
| Out-of-order delivery | Per-key revision comparison | stale + delete resurrection tests |
| Immutable bronze | Canonical JSON SHA-256 filenames, atomic publish | archive count and immutable replay test |
| Real silver files | PyArrow typed Zstd Parquet + atomic manifest | pq.read_table verification and snapshot retention test |
| Gold analytics | DuckDB SQL grouped by currency | literal expected INR/USD aggregate test |
| Recovery/checkpoints | Reconstruct on startup; exact-row source ack | simulated post-commit publication crash + database replay |
| Schema evolution | Additive nullable typed attribute columns; type registry | additive schema + type-conflict tests |
| Poison records | Durable raw + quarantine reason, no silver mutation | invalid contract parameter tests |
| API security | Env bearer token, fail-closed routes, size bounds | API missing/wrong/correct token and oversized body/batch tests |
| Observability | Process health/local readiness/source freshness/metrics | API tests + Compose smoke evidence |
| Docker | PostgreSQL + worker + API, durable volumes, nonroot | build/smoke evidence in verification.md |
| Managed cloud | DMS/Kinesis/Glue/Iceberg/Athena Terraform + PySpark | Terraform validate; cloud execution explicitly unverified |
| Reproducible performance | Measured benchmark + raw timings + scope | evidence/benchmark.json |
| DevOps delivery | CI lint/tests/audit/build/Terraform, manual OIDC plan | workflow code; hosted run status only once actually executed |
| Documentation | Architecture, ADRs, security, runbook, interview | docs/ and SECURITY.md |

See evidence/verification.md for exact pass counts and limitations. A mapped implementation is not evidence of managed deployment.

Public exposure and request-mode source replay have additional traceability in evidence/public-host-hardening.md, with60-test PostgreSQL-backed suites on Python3.12 and3.15, actual read-only-container HTTP verification, and a fresh complete image/secret scan.
