# Selected-key inspection verification — 2026-10-30

This records the bounded private diagnostic and documentation refresh. Hosted deployment/release checks remain in [public-release-verification.json](public-release-verification.json); this change does not claim a new hosted deployment or CI pass.

## Test-first evidence

Before implementation, `python -m pytest -q tests/test_inspection.py --tb=short` produced **3 expected failures**: the private route returned 404 instead of 401, and the two functional tests could not import the missing `fluxlake.inspection` module. After implementation, seven targeted tests passed against actual PostgreSQL 16.6.

Review then added `test_inspection_preserves_scalar_types_in_payload_comparison`. It failed with `[]` instead of `['silver_payload']` because Python equates `True` and `1`. Comparing canonical typed JSON fixed both silver and state payload comparisons; that regression passed before final verification.

## Contract verified

- Authenticated `GET /inspection?key=A&key=B` accepts 1–100 submitted safe keys; distinct keys are sorted/deduplicated. Missing/unsafe/too many keys return 422; anonymous use returns 401 with configured token.
- Under the local writer lock, capture selected SQLite state and one immutable Parquet observation. Compare with latest retained outbox events inside a read-only PostgreSQL repeatable-read transaction, returning source snapshot ID/time and Parquet file/time.
- Match, drift, deletes/tombstones, absence, event identity, state/silver content, scalar types and duplicate silver keys are tested. A real concurrent source commit after source snapshot acquisition remains excluded from the current inspection.
- Manifest bytes and source acknowledgements remain unchanged. Request mode exposes cold-instance missing state before a normal data read invokes replay. Inspection does not refresh first, replay, acknowledge or repair.
- Source/storage failures and exceeded bounds return sanitized 503 without credentials or raw values. Tested limits include source-event size and local snapshot row count; the code also bounds selected aggregate bytes and file size.
- Scope remains selected keys and two observations. Tests do not establish whole-database equality, historical completeness, source-table/trigger equivalence or a globally atomic distributed view.

## Executed checks

Final Windows/Python 3.12.0 run: **68 passed**, zero skips, two visible upstream Starlette/httpx and AnyIO deprecation warnings, 53.88s. [JUnit](inspection-junit.xml). The suite ran against a dedicated actual PostgreSQL 16.6 database on Docker Desktop, not a SQL mock.

Final pinned Linux/Python 3.15.1 verify-image run after the scalar-type fix: **68 passed**, zero skips, the same two visible upstream warnings, 34.73s. [Native-runtime JUnit](inspection-python315-junit.xml). It uses a separate actual PostgreSQL 16.6 database via Docker Desktop host networking.

The final minimal nonroot `fluxlake:inspection` runtime image also built successfully. An actual HTTP smoke ran it as UID/GID 10001 with a read-only root, dropped capabilities, no-new-privileges and a noexec `/tmp` tmpfs, against an isolated real PostgreSQL source. Cold inspection reported missing projection, a normal source read replayed into Parquet, inspection matched, and a subsequent real source update produced drift. Source acknowledgements remained zero. Anonymous inspection returned 401, request-mode fixture writes 403, and an untrusted Host 400. [HTTP runtime evidence](inspection-runtime-smoke.json). The temporary smoke container was removed; other projects were untouched.

Ruff lint and format checks passed (19 Python files). `python -m pip check` reported no broken requirements. `docker compose config --quiet` and `git diff --check` succeeded. Runtime dependency audit reported **zero known vulnerabilities**: [audit JSON](inspection-dependency-audit.json); pip-audit emitted its visible recommendation to add hashes to pinned requirements. Dependency pins and base image digests are unchanged.

The digest-pinned Docker verify target built successfully with real PyArrow 26.0.0, DuckDB 2.0.0 and Psycopg 3.3.6 native libraries. No new runtime dependency was added. The new diagnostic uses the existing source SELECT privilege.

## Fresh benchmark

[Raw samples](benchmark-inspection.json): Windows 11 build 26300, Python 3.12.0, PyArrow 26.0.0, DuckDB 2.0.0, FileLock 4.2.1, Psycopg 3.3.6. 200 measured events in 20 batches of ten; ten warmup events excluded. p50 **193.919 ms**, p95 **273.138 ms**, p99 **320.891 ms**, **49.610 events/s**.

This includes bronze fsync, SQLite commit and full Parquet snapshot publication; excludes PostgreSQL polling, network, inspection and AWS. p99 equals the maximum of twenty observations. Other local project containers were running, and hardware/storage isolation was not controlled. This is a small reproducible sink sample, not a production SLO or cloud-capacity result.

## Limits retained

Hosted GitHub Actions cannot start because of the existing account-level runner restriction. No workflows were changed. AWS managed execution is unprovisioned; prior Terraform provider-schema validation remains historical, not newly rerun. The existing local single-node/full-rewrite and request-mode complete-history/5000-event limits remain. Public release URLs and old scan artifacts are separate dated evidence, not new checks in this task.
