# Upload prebuilt zips or build in CI
resource "aws_lambda_function" "oauth" {
  function_name = "${local.name_prefix}-oauth"
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.11"
  filename      = "${path.module}/oauth_gateway.zip"
  source_code_hash = filebase64sha256("${path.module}/oauth_gateway.zip")
  timeout       = 15
  environment {
    variables = {
      FYERS_CLIENT_ID   = var.fyers_client_id
      FYERS_SECRET_KEY  = var.fyers_secret_key
      FYERS_REDIRECT_URI= var.redirect_url
      SECRETS_NAME      = aws_secretsmanager_secret.fyers.name
    }
  }
  tags = local.tags
}

resource "aws_apigatewayv2_api" "http_api" {
  name          = "${local.name_prefix}-http"
  protocol_type = "HTTP"
  tags          = local.tags
}

resource "aws_apigatewayv2_integration" "oauth" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.oauth.arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "oauth_route" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "GET /oauth/callback"
  target    = "integrations/${aws_apigatewayv2_integration.oauth.id}"
}

resource "aws_lambda_permission" "apigw_invoke_oauth" {
  statement_id  = "AllowInvokeByAPIGW"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.oauth.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}

output "oauth_authorize_url" {
  value = "${aws_apigatewayv2_api.http_api.api_endpoint}/oauth/callback"
}
