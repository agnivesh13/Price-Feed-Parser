# Bucket for Glue script (reuse processed bucket or create separate)
resource "aws_s3_object" "glue_script" {
  bucket = aws_s3_bucket.processed.id
  key    = "glue-scripts/corrected_aggregate_job.py"
  source = "${path.module}/../..//glue/corrected_aggregate_job.py"
  etag   = filemd5("${path.module}/../..//glue/corrected_aggregate_job.py")
}

resource "aws_glue_job" "ohlcv_agg" {
  name     = "${local.name_prefix}-agg"
  role_arn = aws_iam_role.glue_role.arn
  glue_version = "4.0"
  number_of_workers = 2
  worker_type = "G.1X"
  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.processed.bucket}/glue-scripts/corrected_aggregate_job.py"
  }
  default_arguments = {
    "--job-language"  = "python"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-metrics" = "true"
    "--INPUT_PREFIX"  = "s3://${aws_s3_bucket.raw.bucket}/ohlcv/raw/"
    "--OUTPUT_PREFIX" = "s3://${aws_s3_bucket.processed.bucket}/processed/"
  }
  tags = local.tags
}
