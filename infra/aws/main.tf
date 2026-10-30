terraform {
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" { region = var.region }
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

variable "region" { type = string }
variable "name" {
  type    = string
  default = "fluxlake"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "Use a short lower-case resource prefix."
  }
}
variable "private_subnet_ids" { type = list(string) }
variable "dms_security_group_ids" { type = list(string) }
variable "source_database_name" { type = string }
variable "source_secret_arn" {
  type        = string
  description = "Existing Secrets Manager secret: username,password,host,port for WAL-enabled PostgreSQL."
}
variable "source_secret_access_role_arn" {
  type        = string
  description = "Existing IAM role trusted by regional DMS with access to source secret (and KMS if used)."
}
variable "dms_vpc_role_ready" {
  type        = bool
  default     = false
  description = "Explicit acknowledgement that account's dms-vpc-role managed by administrator exists."
}
locals {
  bucket   = "${var.name}-${data.aws_caller_identity.current.account_id}-${var.region}"
  database = replace(var.name, "-", "_")
}
resource "aws_s3_bucket" "lake" { bucket = local.bucket }
resource "aws_s3_bucket_public_access_block" "lake" {
  bucket                  = aws_s3_bucket.lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "lake" {
  bucket = aws_s3_bucket.lake.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "lake" {
  bucket = aws_s3_bucket.lake.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_policy" "tls" {
  bucket = aws_s3_bucket.lake.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.lake.arn, "${aws_s3_bucket.lake.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_kinesis_stream" "cdc" {
  name             = "${var.name}-cdc"
  retention_period = 168
  encryption_type  = "KMS"
  kms_key_id       = "alias/aws/kinesis"
  stream_mode_details { stream_mode = "ON_DEMAND" }
}
resource "aws_iam_role" "dms_stream" {
  name               = "${var.name}-dms-stream"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "dms.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "dms_stream" {
  role = aws_iam_role.dms_stream.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["kinesis:DescribeStream", "kinesis:PutRecord", "kinesis:PutRecords"], Resource = aws_kinesis_stream.cdc.arn
  }] })
}
resource "aws_dms_replication_subnet_group" "cdc" {
  replication_subnet_group_id          = "${var.name}-private"
  replication_subnet_group_description = "Private subnets with source reachability and Kinesis HTTPS egress"
  subnet_ids                           = var.private_subnet_ids
}
resource "aws_dms_replication_instance" "cdc" {
  replication_instance_id     = var.name
  replication_instance_class  = "dms.t3.medium"
  allocated_storage           = 50
  publicly_accessible         = false
  multi_az                    = false
  auto_minor_version_upgrade  = true
  replication_subnet_group_id = aws_dms_replication_subnet_group.cdc.id
  vpc_security_group_ids      = var.dms_security_group_ids
  lifecycle {
    precondition {
      condition     = var.dms_vpc_role_ready
      error_message = "Administrator must create dms-vpc-role with AmazonDMSVPCManagementRole and confirm prerequisites."
    }
  }
}
resource "aws_dms_endpoint" "source" {
  endpoint_id                     = "${var.name}-postgres"
  endpoint_type                   = "source"
  engine_name                     = "postgres"
  database_name                   = var.source_database_name
  ssl_mode                        = "require"
  secrets_manager_arn             = var.source_secret_arn
  secrets_manager_access_role_arn = var.source_secret_access_role_arn
}
resource "aws_dms_endpoint" "stream" {
  endpoint_id   = "${var.name}-kinesis"
  endpoint_type = "target"
  engine_name   = "kinesis"
  kinesis_settings {
    stream_arn                  = aws_kinesis_stream.cdc.arn
    service_access_role_arn     = aws_iam_role.dms_stream.arn
    message_format              = "json"
    include_transaction_details = true
    include_partition_value     = true
  }
}
resource "aws_dms_replication_task" "cdc" {
  replication_task_id      = var.name
  replication_instance_arn = aws_dms_replication_instance.cdc.replication_instance_arn
  source_endpoint_arn      = aws_dms_endpoint.source.endpoint_arn
  target_endpoint_arn      = aws_dms_endpoint.stream.endpoint_arn
  migration_type           = "full-load-and-cdc"
  table_mappings = jsonencode({ rules = [{
    "rule-type"      = "selection", "rule-id" = "1", "rule-name" = "outbox", "rule-action" = "include",
    "object-locator" = { "schema-name" = "public", "table-name" = "transaction_outbox" }
  }] })
  replication_task_settings = jsonencode({
    TargetMetadata   = { BatchApplyEnabled = false },
    Logging          = { EnableLogging = true },
    FullLoadSettings = { TargetTablePrepMode = "DO_NOTHING" }
  })
  depends_on = [aws_iam_role_policy.dms_stream]
}
resource "aws_iam_role" "glue" {
  name               = "${var.name}-glue"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "glue.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "glue" {
  role = aws_iam_role.glue.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = aws_s3_bucket.lake.arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.lake.arn}/*" },
    { Effect = "Allow", Action = ["kinesis:DescribeStream", "kinesis:DescribeStreamSummary", "kinesis:ListShards", "kinesis:GetShardIterator", "kinesis:GetRecords"], Resource = aws_kinesis_stream.cdc.arn },
    { Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetTable", "glue:CreateTable", "glue:UpdateTable", "glue:GetTables"], Resource = [
      "arn:${data.aws_partition.current.partition}:glue:${var.region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:${data.aws_partition.current.partition}:glue:${var.region}:${data.aws_caller_identity.current.account_id}:database/${local.database}",
    "arn:${data.aws_partition.current.partition}:glue:${var.region}:${data.aws_caller_identity.current.account_id}:table/${local.database}/*"] },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:${data.aws_partition.current.partition}:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws-glue/*" }
  ] })
}
resource "aws_glue_catalog_database" "lake" { name = local.database }
resource "aws_s3_object" "job" {
  bucket = aws_s3_bucket.lake.id
  key    = "jobs/glue_job.py"
  source = "${path.module}/glue_job.py"
  etag   = filemd5("${path.module}/glue_job.py")
}
resource "aws_glue_job" "cdc" {
  name              = var.name
  role_arn          = aws_iam_role.glue.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2
  max_retries       = 1
  timeout           = 2880
  execution_property { max_concurrent_runs = 1 }
  command {
    name            = "gluestreaming"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.lake.id}/${aws_s3_object.job.key}"
  }
  default_arguments = {
    "--STREAM_ARN"                       = aws_kinesis_stream.cdc.arn
    "--BUCKET"                           = aws_s3_bucket.lake.id
    "--DATABASE"                         = local.database
    "--datalake-formats"                 = "iceberg"
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--conf" = join(" --conf ", [
      "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
      "spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog",
      "spark.sql.catalog.glue_catalog.warehouse=s3://${aws_s3_bucket.lake.id}/silver/",
      "spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog",
      "spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO"
    ])
  }
  depends_on = [aws_iam_role_policy.glue]
}
resource "aws_athena_workgroup" "lake" {
  name = var.name
  configuration {
    enforce_workgroup_configuration = true
    bytes_scanned_cutoff_per_query  = 1073741824
    result_configuration {
      output_location = "s3://${aws_s3_bucket.lake.id}/athena/"
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
}
output "bucket" { value = aws_s3_bucket.lake.id }
output "glue_job" { value = aws_glue_job.cdc.name }
output "dms_task_arn" { value = aws_dms_replication_task.cdc.replication_task_arn }
output "athena_workgroup" { value = aws_athena_workgroup.lake.name }
