# Managed AWS profile

This code is an alternative deployment, not evidence that AWS is provisioned. It creates billable DMS, Kinesis, Glue and Athena resources. Local execution uses the Python/Parquet profile.

## Prerequisites

1. Terraform 1.13.5 (supported range >=1.9,<2), AWS credentials from a short-lived role, an account budget and an encrypted remote Terraform backend chosen by your organization.
2. Existing private subnets/security groups with PostgreSQL reachability and HTTPS egress to Kinesis, S3/Glue/CloudWatch as needed. No public DMS instance is created.
3. Existing PostgreSQL source with logical replication enabled (`wal_level=logical`; RDS `rds.logical_replication=1` and restart where required), replication-capable DMS user/privileges and retention monitoring. Run `sql/source.sql` for the domain outbox schema. DMS captures only `public.transaction_outbox`; it does not replace that domain trigger.
4. Existing Secrets Manager secret for source `username,password,host,port`, regional DMS-trusted secret-access role with `secretsmanager:GetSecretValue` and KMS decrypt if needed, and account `dms-vpc-role` with `AmazonDMSVPCManagementRole`. Restrict roles to the intended account/source.
5. Source TLS certificate validation policy. This template uses `ssl_mode=require` (encrypted TLS); production should configure `verify-full` and the required DMS certificate to verify server identity.

The provided template references secret ARNs and never reads their plaintext values into Terraform. Do not put credentials into tfvars. `dms_vpc_role_ready=true` explicitly acknowledges the administrator prerequisites; it does not create the account-wide role.

## Validate and deploy deliberately

```powershell
terraform -chdir=infra/aws init -backend=false
terraform -chdir=infra/aws validate
terraform -chdir=infra/aws fmt -check
# Configure a remote state backend before apply; create an ignored deployment.tfvars:
# region = "ap-south-1"
# private_subnet_ids = ["subnet-..."]
# dms_security_group_ids = ["sg-..."]
# source_database_name = "fluxlake"
# source_secret_arn = "arn:aws:secretsmanager:..."
# source_secret_access_role_arn = "arn:aws:iam::...:role/..."
# dms_vpc_role_ready = true
terraform -chdir=infra/aws plan -var-file=deployment.tfvars -out=reviewed.tfplan
# Review resource costs, IAM and network reachability, then:
terraform -chdir=infra/aws apply reviewed.tfplan
```

The template creates a replication task but **does not start it**. Test both DMS endpoint connections and inspect SSL/network errors first. Start its `full-load-and-cdc` migration with the AWS console or `aws dms start-replication-task --replication-task-arn ... --start-replication-task-type start-replication`. Existing outbox history is full-loaded before continuous WAL capture. Start Glue using `aws glue start-job-run --job-name fluxlake`. The manual OIDC workflow produces a plan using configured repository environment variables and an AWS role restricted to that repo/environment; it does not auto-apply.

## Data and ordering

Kinesis receives the default DMS JSON envelope (`data` + `metadata`) for the outbox. `data.aggregate_id`, `version`, `event_id`, `operation`, `occurred_at` and nested/string `data` are normalized by the actual PySpark job. Domain `operation=delete` is an INSERT in the outbox; do not filter using DMS metadata.operation. Subsequent `processed_at` updates repeat the same domain envelope and are harmless in silver.

The job appends raw incoming envelopes to S3 bronze, validates required fields, quarantines malformed/equal-version conflicts, reduces each microbatch to the highest valid revision per key and MERGEs only newer revisions into a format-v2 Iceberg table. `deleted=true` is retained as a tombstone so older events cannot resurrect a deleted key. Stream partition ordering is not trusted for state correctness. One concurrent job and a stable S3 checkpoint prefix prevent competing streaming runs. Bronze records are append-only arrival evidence and may duplicate during retry.

Schema strategy: extras remain in `attributes_json`; deliberate `ALTER TABLE ... ADD COLUMN` promotes new analytics fields. DMS/Glue envelope encoding and Iceberg restart behavior must be integration-tested in a sandbox. Terraform validation cannot prove that a live DMS source emits the expected JSON.

## Athena query

Use the Terraform-created workgroup (encrypted results, enforced 1 GiB/query scan cap):

```sql
SELECT currency, count(*) AS transaction_count, sum(amount_minor) AS total_minor
FROM fluxlake.transactions
WHERE NOT deleted AND status='settled'
GROUP BY currency;
```

No FX conversion is performed. A named view can be created from `sql/gold.sql`. Athena caller IAM is intentionally external: grant users only the needed Glue, S3 and Athena workgroup access.

## Operational checks before production

Exercise insert/update/delete, duplicate CDC delivery, stale versions, source rollback, Glue stop/restart using the same checkpoint, DMS reconnect, Kinesis shard changes and quarantine inspection. Compare resulting state with PostgreSQL using a reconciler or a bounded snapshot. Measure source commit → Athena-visible latency including the configured 30-second microbatch. Set budget alarms; a streaming Glue job and DMS instance incur ongoing costs even when the source is idle. Use multi-AZ DMS and stronger customer-managed KMS controls when requirements warrant them.

This template defaults to a small single-AZ DMS instance and two Glue G.1X workers; these are demonstrator sizing choices, not production recommendations. Stop jobs/tasks when idle. The nonempty versioned bucket is not force-destroyed; preserve/archive or explicitly clear retained versions only after a retention decision.

## Primary sources

- [PostgreSQL row locking / SKIP LOCKED](https://www.postgresql.org/docs/current/sql-select.html)
- [DMS Kinesis target: duplicates and transaction metadata](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.Kinesis.html)
- [Glue streaming connection options](https://docs.aws.amazon.com/glue/latest/dg/glue-streaming-connections.html)
- [GlueContext streaming APIs](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-api-crawler-pyspark-extensions-glue-context.html)
- [Iceberg in AWS Glue](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-format-iceberg.html)
- [Apache Iceberg Spark writes / MERGE](https://iceberg.apache.org/docs/latest/spark-writes/)

Accounts governed by Lake Formation may need explicit database/table permissions for the Glue role in addition to the IAM policy supplied here. Existing organizational SCPs, private endpoint policies and KMS grants remain account prerequisites; review them in the sandbox rather than broadening the job role blindly.
