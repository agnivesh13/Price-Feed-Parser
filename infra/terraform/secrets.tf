resource "aws_secretsmanager_secret" "fyers" {
  name = "${local.name_prefix}/fyers"
  tags = local.tags
}

# Initial secret string placeholder (empty tokens until first OAuth)
resource "aws_secretsmanager_secret_version" "fyers" {
  secret_id     = aws_secretsmanager_secret.fyers.id
  secret_string = jsonencode({
    client_id     = var.fyers_client_id
    app_secret    = var.fyers_secret_key
    access_token  = ""
    refresh_token = ""
    last_updated  = ""
  })
}
