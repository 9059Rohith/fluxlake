# Architecture decisions

## ADR 001 — Outbox locally; DMS WAL CDC in the managed profile

Accepted. A PostgreSQL trigger writes the business change and event envelope together. Polling the transactional outbox runs on a laptop without replication-slot infrastructure, and provides an honest working CDC pattern. It adds write amplification and requires application schema changes. The AWS alternative genuinely captures WAL through DMS, using the outbox envelope for stable domain ordering. We do not call the local poller logical replication.

## ADR 002 — Integer money and per-key ordering

Accepted. Transaction amounts use int64 minor units. Gold groups by currency; there is no accidental FX conversion. A separate revision ledger survives deletes. Revisions, not clocks or outbox sequence IDs, decide which after image wins. Same key/version conflicts quarantine instead of arbitrary last-write-wins.

## ADR 003 — Durable SQLite state plus Parquet snapshots locally

Accepted. SQLite provides atomic receipts, state and tombstones under a local process lock. Real PyArrow produces typed Parquet files and an atomic manifest gives readers a complete snapshot. Commit-to-publication gaps recover on startup. This is compact and testable, with single-node and O(N) rewrite limitations. Managed Iceberg replaces snapshot rewrites for larger workloads.

## ADR 004 — Ack individual source records

Accepted. PostgreSQL sequences do not represent transaction commit order. A row can allocate a lower ID and commit after a larger ID has been consumed. `processed_at` for each row avoids skipped events; `SKIP LOCKED` supports concurrent relay claims. Sink/source distributed atomicity is achieved as replay plus idempotence, not XA.

## ADR 005 — Poison records are durable outcomes

Accepted. Bronze retains input bytes; quarantine stores a stable digest and reason without exposing raw data through the API. A durably quarantined input is acknowledged at the source so one invalid record cannot block the queue. Corrected events need a new event ID and higher revision where required. Audit/replay retains original evidence.

## ADR 006 — Cloud deployment is opt-in and evidence-scoped

Accepted. Terraform creates billable resources only through a deliberate apply in a configured account. The manual OIDC CI workflow produces a plan, not an apply. Secrets are referenced by ARN; no AWS credentials or source passwords enter HCL. Terraform validates provider schema; Glue behavior requires a live sandbox integration test. No status badge claims a run that has not happened.
