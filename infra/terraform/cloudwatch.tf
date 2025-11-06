# Ingestion Lambda (zipped in CI)
resource "aws_lambda_function" "ingest" {
  function_name = "${local.name_prefix}-ingest"
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.11"
  filename      = "${path.module}/ingest_history.zip"
  source_code_hash = filebase64sha256("${path.module}/ingest_history.zip")
  timeout       = 900
  memory_size   = 1024
  environment {
    variables = {
      S3_BUCKET          = aws_s3_bucket.raw.bucket
      TICKER_S3_PATH     = "s3://${aws_s3_bucket.config.bucket}/tickers/tickers.txt"
      FYERS_SECRET_NAME  = aws_secretsmanager_secret.fyers.name
      AWS_REGION         = var.aws_region
      FYERS_HISTORY_URL  = "https://api-t1.fyers.in/data/history"
      FYERS_REFRESH_URL  = "https://api-t1.fyers.in/api/v3/validate-refresh-token"
      MAX_PER_SEC        = "9"
      MAX_PER_MIN        = "180"
      MAX_CONCURRENCY    = "6"
      MAX_ATTEMPTS       = "5"
      DLQ_PREFIX         = "ohlcv/errors/"
      RAW_PREFIX         = "ohlcv/raw/"
      ENABLE_CLOUDWATCH  = "1"
      CW_NAMESPACE       = "PriceFeedParser/Ingest"
      INGEST_TAGS        = "prod"
    }
  }
  tags = local.tags
}

# Schedule ingestion (adjust cron in tfvars if needed)
resource "aws_cloudwatch_event_rule" "ingest_schedule" {
  name                = "${local.name_prefix}-ingest-schedule"
  schedule_expression = var.ingest_schedule_cron
  tags                = local.tags
}

resource "aws_cloudwatch_event_target" "ingest_target" {
  rule      = aws_cloudwatch_event_rule.ingest_schedule.name
  target_id = "ingest-lambda"
  arn       = aws_lambda_function.ingest.arn
}

resource "aws_lambda_permission" "events_invoke_ingest" {
  statement_id  = "AllowEventsInvokeIngest"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ingest_schedule.arn
}
