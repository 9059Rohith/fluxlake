"""Managed Glue 5.0 streaming job: DMS outbox WAL envelopes → bronze → Iceberg.

DMS captures public.transaction_outbox; the domain operation lives in the outbox's
operation column (distinct from DMS metadata.operation). Acks update the outbox,
so repeated envelopes are expected and the key/version MERGE is idempotent.
Run one concurrent job; use the same checkpoint for recovery.
"""

import sys

from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark import SparkContext
from pyspark.sql import Window, functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType

args = getResolvedOptions(sys.argv, ["JOB_NAME", "STREAM_ARN", "BUCKET", "DATABASE"])
glue = GlueContext(SparkContext.getOrCreate())
spark = glue.spark_session
job = Job(glue)
job.init(args["JOB_NAME"], args)
# Names originate in Terraform validation, never arbitrary incoming events.
database = args["DATABASE"]
if not database.replace("_", "").isalnum():
    raise ValueError("Invalid catalog database")
table = f"glue_catalog.{database}.transactions"
bucket = args["BUCKET"]
spark.sql(f"""CREATE TABLE IF NOT EXISTS {table} (
    key STRING, version BIGINT, event_id STRING, payload_hash STRING,
    amount_minor BIGINT, currency STRING, status STRING, occurred_at STRING,
    attributes_json STRING, deleted BOOLEAN)
    USING iceberg PARTITIONED BY (bucket(16,key))
    TBLPROPERTIES ('format-version'='2')""")

payload_schema = StructType(
    [
        StructField("amount_minor", LongType()),
        StructField("currency", StringType()),
        StructField("status", StringType()),
    ]
)


def process_batch(batch, batch_id):
    if batch.rdd.isEmpty():
        return
    batch.persist()
    try:
        # Every arrival gets immutable append-only raw evidence; retries may append raw
        # duplicates. Silver resulting state deduplicates them.
        raw = batch.select(F.to_json(F.struct("*")).alias("raw"))
        raw.write.mode("append").json(f"s3://{bucket}/bronze/batch={batch_id}/")
        normalized = raw.select(
            F.get_json_object("raw", "$.data.aggregate_id").alias("key"),
            F.get_json_object("raw", "$.data.version").cast("long").alias("version"),
            F.get_json_object("raw", "$.data.event_id").alias("event_id"),
            F.get_json_object("raw", "$.data.operation").alias("operation"),
            F.get_json_object("raw", "$.data.occurred_at").alias("occurred_at"),
            F.get_json_object("raw", "$.data.data").alias("attributes_json"),
            "raw",
        ).withColumn("payload", F.from_json("attributes_json", payload_schema))
        normalized = normalized.select(
            "key",
            "version",
            "event_id",
            "occurred_at",
            "attributes_json",
            "operation",
            "raw",
            F.col("payload.amount_minor").alias("amount_minor"),
            F.col("payload.currency").alias("currency"),
            F.col("payload.status").alias("status"),
            (F.col("operation") == "delete").alias("deleted"),
        ).withColumn(
            "payload_hash",
            F.sha2(
                F.to_json(
                    F.struct(
                        "key", "version", "event_id", "operation", "occurred_at", "attributes_json"
                    )
                ),
                256,
            ),
        )
        valid = (
            F.col("key").rlike("^[A-Za-z0-9_-]{1,128}$")
            & (F.col("version") > 0)
            & F.col("event_id").isNotNull()
            & F.to_timestamp("occurred_at").isNotNull()
            & F.col("operation").isin("insert", "update", "delete")
            & (
                F.col("deleted")
                | (
                    (F.col("amount_minor") >= 0)
                    & F.col("currency").rlike("^[A-Z]{3}$")
                    & F.col("status").isin("pending", "settled", "failed")
                )
            )
        )
        valid = F.coalesce(valid, F.lit(False))
        normalized.where(~valid).withColumn("reason", F.lit("invalid_contract")).write.mode(
            "append"
        ).json(f"s3://{bucket}/quarantine/")
        candidates = normalized.where(valid)
        # An equal key/version with conflicting bodies is quarantined instead of
        # choosing an arbitrary winner, including conflicts inside the same microbatch.
        conflict_keys = (
            candidates.groupBy("key", "version")
            .agg(F.countDistinct("payload_hash").alias("variants"))
            .where("variants > 1")
            .select("key", "version")
        )
        candidates.join(conflict_keys, ["key", "version"], "inner").withColumn(
            "reason", F.lit("batch_version_conflict")
        ).write.mode("append").json(f"s3://{bucket}/quarantine/")
        candidates = candidates.join(conflict_keys, ["key", "version"], "left_anti")
        existing = spark.table(table).select("key", "version", "payload_hash").alias("t")
        conflict = (
            candidates.alias("s")
            .join(
                existing,
                (F.col("s.key") == F.col("t.key"))
                & (F.col("s.version") == F.col("t.version"))
                & (F.col("s.payload_hash") != F.col("t.payload_hash")),
                "inner",
            )
            .select("s.*")
        )
        conflict.withColumn("reason", F.lit("stored_version_conflict")).write.mode("append").json(
            f"s3://{bucket}/quarantine/"
        )
        candidates = candidates.join(
            conflict.select("key", "version").distinct(), ["key", "version"], "left_anti"
        )
        latest = candidates.withColumn(
            "rn",
            F.row_number().over(
                Window.partitionBy("key").orderBy(F.desc("version"), F.desc("event_id"))
            ),
        ).where("rn=1")
        latest.select(
            "key",
            "version",
            "event_id",
            "payload_hash",
            "amount_minor",
            "currency",
            "status",
            "occurred_at",
            "attributes_json",
            "deleted",
        ).createOrReplaceTempView("incoming")
        spark.sql(f"""MERGE INTO {table} t USING incoming s ON t.key=s.key
            WHEN MATCHED AND s.version>t.version THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *""")
    finally:
        batch.unpersist()


source = glue.create_data_frame.from_options(
    connection_type="kinesis",
    connection_options={
        "streamARN": args["STREAM_ARN"],
        "startingPosition": "TRIM_HORIZON",
        "inferSchema": "true",
        "classification": "json",
        "emitConsumerLagMetrics": "true",
    },
)
glue.forEachBatch(
    frame=source,
    batch_function=process_batch,
    options={
        "windowSize": "30 seconds",
        "checkpointLocation": f"s3://{bucket}/checkpoints/outbox-v1/",
        "batchMaxRetries": 3,
    },
)
job.commit()
