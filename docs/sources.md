# Primary-source references

Researched 2026-10-30. Source claims are limited to the design points below.

| Design point | Primary source |
|---|---|
| `SKIP LOCKED` can support queue-like consumers and has inconsistent general-query semantics | [PostgreSQL SELECT locking clause](https://www.postgresql.org/docs/current/sql-select.html) |
| Kinesis target does not deduplicate and DMS transaction metadata must be enabled | [AWS DMS Kinesis target](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.Kinesis.html) |
| Kinesis Glue stream options and inference | [AWS Glue streaming connections](https://docs.aws.amazon.com/glue/latest/dg/glue-streaming-connections.html) |
| Glue `forEachBatch` checkpoint API | [GlueContext APIs](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-api-crawler-pyspark-extensions-glue-context.html) |
| Iceberg catalog and Spark extension configuration | [AWS Glue Iceberg](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-format-iceberg.html) |
| Conditional MERGE updates in Spark Iceberg | [Apache Iceberg Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/) |

The local implementation and guarantees are supported by repository tests, not inferred from cloud documentation. Managed integration is a separate verification boundary.
