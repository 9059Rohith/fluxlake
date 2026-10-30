# Operations runbook

## Healthy operation

- `/health`: API process can respond. In polling mode `/ready` checks local SQLite integrity and snapshot availability; it does not prove source reachability. In request mode `/ready` also invokes bounded source replay and returns 503 if replay is unavailable (with the documented five-second cache).
- `/pipeline`: last successful relay poll, age, and fresh/stale/unknown status (60-second threshold). Empty polls also advance heartbeat.
- `/metrics`: durable applied/duplicate/stale/quarantined delivery outcomes and current live row count. Use 5-minute increases/rates in Prometheus; counters persist in SQLite.
- Worker logs JSON batch summaries and retry error types without database URLs or raw records. Query `count(*)` and oldest `occurred_at` where `processed_at IS NULL` for source queue backlog and age.

Suggested alerts: source heartbeat age >60 seconds, pending oldest age >120 seconds, quarantine increase, disk free <20%, worker retry rate, API 5xx. Treat thresholds as demo starting points, not measured SLOs.

## Source outage

In polling mode the relay retries connection/storage errors with exponential backoff capped at 30 seconds. The API reads the last committed snapshot. In request mode source-backed reads fail closed with 503 when replay is unavailable, after the documented cache interval. `/pipeline` becomes stale. Check PostgreSQL health, network and credentials without printing secrets. Restore source connectivity; processed rows are already acknowledged and pending rows resume. Restarting never resets source checkpoints.

## Sink failure or interrupted publish

Stop the worker and API writers. Check disk space and volume permissions; preserve the volume. Restart the worker/API: `Lake` reconstructs a fresh snapshot from committed SQLite state. A source batch not acknowledged is replayed and receipts prevent double application. If bronze hash verification fails, preserve the bad file and restore its canonical bytes from a trusted backup; do not delete receipts to hide corruption.

## Quarantine

Fetch authenticated `/quarantine` to get digest and reason; inspect the corresponding local bronze JSON under controlled access. Resolve the source contract, then issue a corrected source write with a new version. For isolated replays, create a separate lake root and feed a JSON array through `fluxlake replay --root replay-data --file corrected.json`. A changed body must not reuse an existing event ID. Archive the original quarantine as evidence.

## Backup and restore

Take a consistent filesystem snapshot of the entire stopped lake volume (SQLite, WAL/SHM when present, bronze, silver, manifest). A plain copy of a live SQLite main file is insufficient. Back up PostgreSQL with its normal supported tools. Restore both lake and source checkpoints together, or clear only the source processed_at values for the desired replay horizon while keeping sink receipts. Restoring source ahead of an older sink without replay loses data. Verify `/gold`, row counts, known revisions and quarantines after recovery.

## Local lifecycle

`docker compose stop` pauses only this project's services. `docker compose up -d` resumes the same named volumes. `docker compose down` removes containers/network but retains volumes. `docker compose down -v` permanently deletes this project's database and lake; use only for explicitly disposable demo data. Preserve the generated PostgreSQL password across restarts of the same volume.

## Managed AWS

Follow `infra/aws/README.md`. Start and test DMS endpoint connections before its replication task; start Glue with the configured stream and unchanged checkpoint location. Monitor DMS source/target latency, Kinesis iterator age/write throttles, Glue batch duration and consumer lag, Iceberg file/snapshot counts, S3 quarantine volume and Athena bytes scanned. Do not reset a checkpoint casually: replay is safe for versioned resulting state, but raw append-only bronze can contain duplicate arrivals.

For teardown, stop Glue and DMS first. Export needed evidence. Terraform destroy removes billable compute/stream resources; the versioned nonempty S3 bucket is intentionally not force-destroyed and requires an explicit retention/deletion decision. Iceberg metadata and historical object versions continue to cost storage until removed.

Source initialization adds `transaction_attributes_safe` as a NOT VALID check to support upgrading an existing demonstration database. New writes are checked immediately; clean pre-existing invalid rows and run `ALTER TABLE transactions VALIDATE CONSTRAINT transaction_attributes_safe` before production migration signoff.

Operational reads, metrics, quarantine and OpenAPI now require a32+byte bearer token. Public synthetic summaries are separate at /demo/summary and require explicit public mode/hostnames. For ephemeral HTTP hosting use the request-triggered read-only profile in hosting.md; never run independent acknowledged workers against disposable sinks.

## Investigate projection drift

1. Choose explicit keys from authenticated `/transactions`, a known business write, or retained source evidence. Send `GET /inspection?key=A&key=B` with the private bearer token. At most 100 submitted keys are accepted; duplicates are normalized.
2. Record `source_snapshot.id/captured_at` and `projection_snapshot.file/captured_at`. These are two observations. A later source commit can explain a newer source revision. Request mode deliberately does not refresh before inspection.
3. Read `differences`: `revision` / `deletion` / `event_identity` / `state_payload` indicate SQLite drift; `state_missing` indicates no local receipt-state for the latest event. `silver_missing`, `silver_unexpected`, `silver_payload` or `silver_duplicate_key` indicate projection shape/content drift. `source_contract` indicates the latest source event violates the sink contract. `source_absent` requires checking history retention and whether arbitrary fixtures were loaded. A key absent everywhere is `absent`, not proof it never existed.
4. Investigate `/pipeline`, `/quarantine`, worker errors and source backlog. In polling mode let the relay consume pending rows; in request mode make a normal data request to invoke bounded history replay. Repeat inspection afterward. Preserve corruption evidence before restarting or replacing caches. No diagnostic result authorizes destructive repair or bypassing quarantine.
5. A 503 means inspection could not establish complete bounded observations: source configuration/privilege/timeouts, local corruption or capacity may be responsible. HTTP output intentionally omits driver details and raw data. Use controlled source/storage checks. A 422 means missing, unsafe or too many keys; 401 means missing/wrong authorization.

Reproducible demo: stop only this project's worker with `docker compose stop worker`, update a selected source transaction, inspect to observe a mismatch, then `docker compose start worker` and inspect after catch-up. The inspection call itself must not change the manifest or `processed_at`. Bounds and snapshot limitations are in [architecture](architecture.md#selected-key-inspection).
