# FluxLake archive recovery benchmark

The Replay audit page shows an offline measurement alongside its live read-only audit of retained GitHub API acquisitions. The downloadable report contains the measured counts, times, source digest, failure observation and independently verified identity digest. [Replay audit](https://rohith-fluxlake.vercel.app/workspace/replay) · [Benchmark evidence](../src/fluxlake/web/archive-replay-benchmark.json)

## Source and admission

The benchmark selects the first 20,000 unique events that meet FluxLake's public-event contract in archive order. The original decoded JSON objects go directly to the publisher. The harness caps each batch at 100 rows and 1,500,000 canonical bytes, and records skipped source lines. The compressed archive is 72,578,615 bytes with upstream object MD5 `432312db553b5e96f65022444dd82e8b` and locally computed SHA-256 `717eaa4e74034a93ef6b423db7f61776f81899f978dba60d8b42b141e6d16429`. [GH Archive methodology](https://www.gharchive.org/) · [2025-01-01 15:00 UTC archive](https://data.gharchive.org/2025-01-01-15.json.gz)

The normal live ingestion and the archive harness share the transactional publisher. The harness supplies its fixed archived source URL and skips the live endpoint's poll interval because it reads a local verified file. Archive receipts identify the historical object and leave per-request HTTP metadata empty. The interrupted batch's original archive-line digest is recorded separately.

## Observed run on 4 November 2026

The cohort contains 20,000 unique events from 20,012 scanned lines, with 12 records excluded by the existing 64 KiB cap. PostgreSQL retained 57,968,885 canonical JSON bytes across 15 event types. The independent identity digest was `6dc04a265f930ffec610a9011eedaa3592797ec73f14cf9323600c1a65167eb4` before and after redelivery.

| Phase | Measured result |
|---|---|
| Process termination → SQL ready | 1.653 s with automatic WAL recovery. The 100 committed bronze and silver rows and their receipt survived. The interrupted publication left zero visible rows or receipt. |
| Retry interrupted batch | 100 exact source records published in 219 ms. |
| Steady publication | 19,800 events in 54.855 s, 360.95 events/s. |
| Full redelivery | 20,000 matching duplicates in 23.536 s, 849.76 events/s. Bronze, silver, quarantine and schema observations stayed stable. 200 duplicate receipts were appended. |
| Bounded read-only audit | 20,000 events reconstructed across 100 audits in 24.152 s, with zero differences. |

The measured Windows x64 run used Python 3.12.0 and PostgreSQL 18.2 with `fsync` and `synchronous_commit` enabled. The downloadable report records exact timings and the restart snapshots.

## Reproduce

Use the repository's Python environment and locally installed PostgreSQL binaries. This measurement uses PostgreSQL 18.2 on Windows. The script initializes a disposable cluster with a generated database password and a loopback-only port, then removes its data directory on exit. The harness constructs its connection from the process it starts.

```powershell
New-Item -ItemType Directory -Force .downloads | Out-Null
curl.exe --fail --retry 7 --continue-at - --output .downloads/2025-01-01-15.json.gz https://data.gharchive.org/2025-01-01-15.json.gz
.venv/Scripts/python.exe scripts/benchmark_archive_replay.py .downloads/2025-01-01-15.json.gz --postgres-bin 'C:/Program Files/PostgreSQL/18/bin' --limit 20000 --output .downloads/archive-benchmark.json
```

Set `--postgres-bin` to the directory that contains `initdb`, `postgres` and `pg_ctl` on the benchmark host. Archive bytes and the new report stay in the ignored `.downloads` directory. The versioned report shipped by the app records a specific observed run.

## Verification sequence

1. Publish the first real batch with the production publisher. Record counts and original provenance.
2. Start the second real batch with a database trigger that confirms pending bronze rows before pausing its silver insert. Observe the actual PostgreSQL writer waiting in that statement. Terminate the isolated PostgreSQL postmaster abruptly and require its process exit and a failed writer call. The Windows run uses TerminateProcess.
3. Restart the same cluster and observe automatic WAL recovery and a new postmaster start time. Compare the restart state with the committed first batch. Remove the pause trigger and publish the exact interrupted inputs.
4. Publish the remaining batches. Independently read both layers with SQL, compare each stored raw JSON object and fingerprint with its source object, compare every typed field and run identity, and reconcile counts by event type.
5. Redeliver all original batches through PostgreSQL. Verify matching duplicate receipts, unchanged bronze/silver/schema state and an identical independent identity manifest. Run the actual bounded read-only audit over all first-publication receipts in pairs and require zero differences.

The identity manifest hashes ASCII lines in lexical event-ID order. Each line contains the ID, a tab, the lowercase SHA-256 of the canonical JSON, a tab, its canonical byte count and a final newline. Each digest is recomputed from the archive object and independently compared against the decoded database JSON and stored checksum.

The timings describe one sequential local run with PostgreSQL connection and transaction costs. The steady publication phase excludes the first committed batch and the crash/retry batch. Download, cohort selection and independent manifest scans are outside the timed phases. Kill-to-SQL-ready includes process interruption, restart and readiness polling. Hosted latency and recovery under concurrent or distributed workloads require separate measurements.
