# Replay audit: design and verification plan

The new public Replay audit page reconstructs the publication contract from actual retained
GitHub bronze records and compares it with silver, immutable hashes, canonical byte counts,
quarantine evidence and acquisition receipts. Select one or two acquisitions; inspect exact
differences, chronological event evidence and download the resulting fingerprinted report.

The existing store retains first accepted JSON, duplicate counts and rejected hashes/reasons.
It does **not** retain individual duplicate bodies, original response bytes, delivery order,
or database log positions. The audit must disclose those limits. Event timestamp order is
only a presentation order. Changed-identity receipts can be reported, but their rejected
field differences cannot be reconstructed. Stale deliveries and exactly-once processing
cannot be established. A separate in-memory second pass over the retained identities is a
clearly labeled controlled redelivery experiment, not an observed source delivery.

Implementation: dependency-free deterministic reducer, bounded read-only repeatable-read
PostgreSQL acquisition (two runs / 200 events / 4 MiB), anonymous GET API, existing CSP-safe
nav/page, same-origin evidence export. No ingestion, writes, rate-counter changes or model
calls. Empty acquisitions remain auditable. Missing selected runs return 404; malformed,
repeated or oversized selections return 422; source capacity failures return sanitized 503.

TDD: first demonstrate missing implementation failures; verify canonical stability, precise
hash/byte/typed-field/missing-row discrepancies, failed/empty receipts, conflict provenance,
input permutation invariance, same-timestamp ordering, changed identity rejection, bounded
capacity and no input mutation. Add route and read-only query tests. Run complete pytest,
Ruff, JS syntax, dependency audit; benchmark controlled worst-case and actual retained input
separately. Deploy existing Vercel project and verify canonical public APIs/UI.

Research (2026-11-02): [GitHub events documentation](https://docs.github.com/en/rest/activity/events)
describes a delayed sampled polling feed. [Debezium PostgreSQL](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)
documents log positions and transaction metadata unavailable in this source. [Iceberg audit
branches](https://iceberg.apache.org/docs/latest/branching/) motivate validating isolated
evidence before publication; this feature is an audit of existing publication, not an Iceberg
branch implementation or mutation.
