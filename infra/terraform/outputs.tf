output "raw_bucket"       { value = aws_s3_bucket.raw.bucket }
output "processed_bucket" { value = aws_s3_bucket.processed.bucket }
output "config_bucket"    { value = aws_s3_bucket.config.bucket }
output "secrets_name"     { value = aws_secretsmanager_secret.fyers.name }
output "oauth_authorize_url" { value = "${aws_apigatewayv2_api.http_api.api_endpoint}/oauth/callback" }
output "glue_job_name"    { value = aws_glue_job.ohlcv_agg.name }
