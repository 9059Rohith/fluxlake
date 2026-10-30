# Interview guide

**Is this WAL CDC?** The local implementation is an application-level transactional outbox captured by a PostgreSQL trigger and polled by a relay. The AWS profile uses DMS WAL capture of that outbox. Being precise about this distinction matters more than using a bigger stack name.

**Why not checkpoint the largest outbox ID?** Identity values are allocated before commit. A lower-ID transaction may commit after a higher-ID transaction has been processed. We acknowledge exact rows; no high-watermark can skip late commits. Per-key revisions order entity state independently of delivery order.

**How do you get exactly once?** We don't promise exactly-once transport. PostgreSQL and the filesystem are not in one distributed transaction. Sink receipts and state commit atomically, then silver publishes, then the source is acknowledged. A crash leaves either uncommitted work or a replay; replay produces one resulting state.

**Why retain tombstones?** Dropping delete metadata lets a delayed insert resurrect a deleted transaction. Keeping the latest revision with deleted=true makes stale deliveries harmless. Tombstone retention must exceed maximum replay age.

**What happens to schema changes?** Local extra scalar attributes add typed nullable Parquet columns. Existing attribute type changes quarantine. The managed profile preserves extras as JSON and promotes columns with reviewed Iceberg schema changes. Required money/currency/status fields remain explicit contracts.

**How does gold avoid wrong money math?** Store integer minor units, never floating-point amounts, and group sums by currency. Currency scale and FX conversion belong in an explicit reference-data model; the demo does not infer USD/JPY scales or mix currencies.

**Why SQLite with Parquet?** Parquet isn't a transactional row store. SQLite gives atomic identity/order state and a manifest makes Parquet publication reader-safe. The local full snapshot rewrite makes correctness inspectable but costs O(live rows) per batch. Iceberg MERGE and scalable object storage are the managed route.

**What DevOps work is substantive?** Reproducible locked dependencies, nonroot/read-only containers, health and source-freshness separation, durable metrics, PostgreSQL integration tests, replay/recovery tests, Docker builds, Terraform provider validation, least-privilege service roles, secret references, a reviewed OIDC plan workflow, and documented restore/teardown boundaries.

**Which performance claims are defensible?** Only the measured local benchmark scope and raw samples in evidence. It reports batch apply latency with fsync, SQLite commit and Parquet publication. It excludes source poll delay, network and all AWS services. End-to-end source freshness depends on the poll interval plus batch processing and load.

**What would you change for production?** Harden database roles and ingress auth, validate DMS envelope fixtures in a live AWS sandbox, set budget/retention policies, extend selected-key inspection into coordinated source-table reconciliation, add distributed processing only after proving throughput needs, compact Iceberg files, and define freshness/error-budget SLOs from observed behavior.

**How do you distinguish a healthy process from correct projected data?** `/health` only proves the process responds. `/ready` checks local state and, in request mode, invokes replay. `/pipeline` reports source synchronization freshness. The authenticated `/inspection?key=A&key=B` compares selected latest retained outbox revisions against SQLite and one immutable Parquet observation without first refreshing or repairing. Its source read uses read-only repeatable-read isolation and reports the PostgreSQL snapshot ID. Revision, tombstone, event identity, state and silver payload differences are explicit. A concurrent-write test proves later commits are excluded from the source observation.

**Does a matching inspection prove the whole database is correct?** No. It covers at most 100 submitted keys and two observed snapshots, not a global atomic view. The reference is latest retained outbox evidence; pruning, a broken/bypassed trigger or source-table divergence requires a separate coordinated reconciliation. An absent key does not prove it never existed. A newer source commit can legitimately create drift. The endpoint is bounded and reports unavailable rather than silently truncating observations.
