# Selected-key projection inspection — settled implementation plan

User opted out of questions and approval. Deliver a bounded diagnostic without modifying source capture or replay.

## Design and interfaces

- New `src/fluxlake/inspection.py`: `inspect(lake: Lake, database_url: str, keys: list[str]) -> dict` and sanitized `InspectionUnavailable`. At most 100 distinct safe identifiers; no credentials or raw payloads in results. Hold the existing local writer lock while reading SQLite state and one immutable Parquet snapshot. Refuse snapshots over 5000 rows and source results over 1 MiB / 64 KiB per event. Read latest retained outbox event per key through indexed lateral lookups in one read-only repeatable-read source transaction, with 5s connection/statement and 2s lock limits.
- Modify `src/fluxlake/api.py`: authenticated `GET /inspection?key=A&key=B`; validation 422, unavailable/over-capacity 503. Diagnostic performs no replay, source ack or repair, even in request mode. A match covers selected keys and observed snapshots only. PostgreSQL current snapshot identifier/time and immutable Parquet filename are returned; no globally atomic or whole-database equality claim.
- New `tests/test_inspection.py`: local comparison tests and actual PostgreSQL integration coverage for match, pending update, stale/resurrection/delete, payload corruption, absence, repeatable-read semantics, bounds, auth, source failure redaction, no mutation. Existing full suites remain required.
- `compose.yaml`: supply API source connection for optional inspection; no new dependencies, privileges, workflows or hosting mutations.
- Rewrite README around purpose, five code-backed capabilities, scope, reproduction and measured evidence. Update architecture, requirements, interview, hosting/runbook docs as needed.

## Execution

1. Write meaningful tests, run and retain failure due to missing endpoint/module.
2. Implement smallest diagnostic; run targeted and full suites against actual dedicated PostgreSQL.
3. Verify pinned Python 3.15 runtime via Docker verify target, lint/format, dependency consistency, relative documentation links, and a fresh recorded benchmark.
4. Record exact results and limitations in evidence; commit source and documentation on main. Root agent owns push/deploy.
