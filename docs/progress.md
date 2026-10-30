# Progress ledger

- 2026-10-30: Read TDD and verification skills. Established scoped repository and test-first implementation plan. Primary source research: PostgreSQL queue row locks, AWS DMS Kinesis duplicate semantics, Apache Iceberg MERGE.
- PostgreSQL 16.6 Compose source started successfully; isolated fluxlake_test database used for integration tests. Full suite: 30 passed, one upstream Starlette/AnyIO deprecation warning before dependency upgrade.
- Regression red→green: reserved envelope attributes, PostgreSQL core-amount attribute override, CLI explicit SQL file, non-finite JSON returns 422.
- First audit found 11 known vulnerabilities in four initially pinned packages. Upgrading dependencies before final signoff; no claim of a clean audit until rechecked.
- Patched final pins verified: full 30-test suite passes on PostgreSQL 16.6; runtime audit checks 21 packages with zero known vulnerabilities; pip check passes. Two upstream test-client deprecation warnings remain visible.
- Terraform 1.13.5 / AWS provider 6.71.0: init and provider-schema validate succeed. Official archive SHA256 hashes (including Linux) retained in dependency lock. Initial stalled direct download was replaced with a verified local mirror.
- Final durable sink benchmarks recorded with raw samples: batch1 p50/p95/p99 102/213/308 ms, 8.51 events/s; batch10 224/388/458 ms, 40.69 events/s. Cloud/source/network excluded.
- Host port 8002 belongs to an unrelated service. FluxLake API uses free 18082, PostgreSQL 55433. Unrelated containers were not modified.

- Independent review found post-commit invalid-surrogate poisoning and non-ASCII header failure. Reproduced red tests, added recursive strict UTF-8 validation before state mutation and byte-safe trimmed/bounded token checks. Added POSIX parent-directory fsync and injected-failure tests proving durability ordering. Final full suite: 39 passed, two visible upstream warnings.
- Final code benchmark rerun: batch1 p50/p95/p99 94.7/236.3/375.1 ms, 8.34 events/s; batch10 192.0/365.9/465.6 ms, 45.83 events/s. Exact samples/version metadata replace earlier measurements.
- Final Docker image built successfully; api and worker run as UID10001, read-only root filesystem, all capabilities dropped. Compose HTTP acceptance passed actual source insert/update/delete, exact INR/USD gold reconciliation, unauthorized401 and valid-token acceptance. Raw non-ASCII authorization returned401 and surrogate JSON quarantined. Restarting worker/API preserved gold and readiness. API available at http://localhost:18082.
