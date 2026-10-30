# Architecture and recovery

## Boundaries

The local source is an application database with an AFTER trigger on INSERT/UPDATE/DELETE. Trigger failure rolls back the business write; a rolled-back business transaction leaves no outbox record. DDL/TRUNCATE are outside the contract. Transaction IDs cannot be updated. The separate per-key revision ledger serializes changes for that key and survives deletes/reinserts.

The relay reads pending rows with `FOR UPDATE SKIP LOCKED`. It holds those source locks through sink publication, then updates only those row IDs. The whole source operation is a PostgreSQL transaction. Two relays may deliver revisions out of order; the sink uses per-key revisions. An outbox identity sequence may be allocated before another transaction commits, so a MAX(id) checkpoint is unsafe and is deliberately absent.

## Local commit protocol

1. Take the lake writer lock (OS-backed file lock; same filesystem across local processes).
2. Canonicalize JSON and hash it with SHA-256. Publish a new raw bronze file through fsynced temporary write + atomic rename; existing hashes must match their bytes.
3. In one SQLite transaction, validate the event, compare receipt identity and current version, and atomically write receipt/current state or quarantine outcome. FULL synchronous WAL mode is used.
4. Commit SQLite before producing a new typed Zstd Parquet snapshot. The schema is a fixed transaction base plus additive nullable `attr_*` columns from the durable attribute registry.
5. Fsync snapshot, then atomically replace the manifest pointer. Readers open the referenced immutable file; old snapshots remain available.
6. Return success; only then does the relay mark its exact source rows processed and commit.

This is exactly-once **resulting state** over at-least-once delivery, not a two-phase distributed transaction. Multi-record source transactions can span relay batches; analytics do not promise atomic visibility across keys.

## Crash matrix

| Crash point | Result | Recovery |
|---|---|---|
| Before bronze publish | Source unacked | Retry input |
| After bronze, before SQLite commit | Extra raw evidence only | Retry input |
| During SQLite transaction | Transaction rolls back | Retry input |
| After SQLite commit, before Parquet manifest | State ahead of silver | Restart reconstructs silver; source stays unacked |
| After manifest, before source ack | Published state, source pending | Replay classified duplicate |
| After source ack | Both durable | Resume pending source rows |

A process crash is tested. Sudden hardware power loss and filesystem/controller write-cache guarantees are environment-dependent; POSIX directory fsync is implemented before raw-object acknowledgement and before/after manifest publication; new directory entries are also synced. Windows uses file fsync plus atomic rename, with process-crash recovery scope. Off-host backups remain necessary. Disk-full errors propagate and keep source rows pending. A corrupted bronze hash is treated as an operational fault, never silently overwritten.

## Schema evolution

Each event carries a complete after image. `data` extras are named scalar attributes (string/int64/bool/finite float), with one type per name for the lifetime of a local lake. New names become nullable typed columns in the next snapshot. Old snapshots keep their schema and immutable contents. A type change is quarantined; deploy a versioned new attribute or migrate deliberately. Removing an attribute produces null on newer after images. Delete events may have empty data. Core required fields never evolve implicitly.

The managed profile keeps evolving extras in `attributes_json`, avoiding a live schema-inference change in Iceberg. Promote frequently queried attributes through explicit reviewed Iceberg `ALTER TABLE ADD COLUMN` and backfill. Core incompatible changes go to S3 quarantine. This managed strategy differs intentionally from local additive columns.

## Managed profile

DMS performs PostgreSQL WAL capture on the outbox table. Capturing its domain envelope gives Glue the same monotone per-key revision even for a delete and subsequent reinsert. DMS metadata.operation describes the outbox table change, while outbox `operation` describes the business action. Source acknowledgement updates can generate duplicate CDC envelopes. Glue writes raw envelopes before validation, quarantines bad/equal-version conflicts, chooses the latest revision per key in each microbatch, and MERGEs only larger revisions. Iceberg retains deleted rows as tombstones; Athena views filter them. Kinesis/Spark checkpoints track stream progress, not application revision order.

Managed job is deployable code with Terraform validation but no live Glue execution evidence. Do not infer AWS correctness solely from local tests. Validate real DMS JSON encoding and restart/reshard behavior in a sandbox before production.

## Scaling and retention

The local snapshot rewrite is O(live rows) per batch. Larger batches improve throughput at the cost of freshness. Bronze, receipts, tombstones and snapshots grow without automatic deletion; this favors reproducible recovery over unattended bounded storage. Before long-running use, establish legal retention, compact old snapshots after all readers expire, and retain tombstones for at least the maximum replay horizon. Cloud Iceberg supports scalable file management and snapshots; schedule compaction and snapshot expiry only after measuring file counts and retention needs.

The default source never prunes outbox history. Managed full-loading the outbox reconstructs complete state only while that complete history is retained. If outbox history is pruned, bootstrapping a new sink requires a consistent business-table snapshot plus a coordinated CDC position; merely full-loading the remaining outbox is insufficient. Kinesis retains seven days here; an outage beyond that window needs an explicit outbox replay/rebootstrap, not silent checkpoint reset.
