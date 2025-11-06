# Lambda role for oauth & ingest
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service" identifiers = ["lambda.amazonaws.com"] }
  }
}

resource "aws_iam_role" "lambda_role" {
  name               = "${local.name_prefix}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Access to S3, Secrets Manager, CloudWatch, Glue (as needed)
data "aws_iam_policy_document" "lambda_inline" {
  statement {
    sid     = "S3Access"
    actions = ["s3:GetObject","s3:PutObject","s3:ListBucket"]
    resources = [
      aws_s3_bucket.raw.arn,
      "${aws_s3_bucket.raw.arn}/*",
      aws_s3_bucket.processed.arn,
      "${aws_s3_bucket.processed.arn}/*",
      aws_s3_bucket.config.arn,
      "${aws_s3_bucket.config.arn}/*",
    ]
  }
  statement {
    sid     = "SecretsAccess"
    actions = ["secretsmanager:GetSecretValue","secretsmanager:UpdateSecret"]
    resources = [aws_secretsmanager_secret.fyers.arn]
  }
  statement {
    sid     = "CloudWatchPutMetrics"
    actions = ["cloudwatch:PutMetricData"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "lambda_inline" {
  name   = "${local.name_prefix}-lambda-inline"
  policy = data.aws_iam_policy_document.lambda_inline.json
}

resource "aws_iam_role_policy_attachment" "lambda_inline_attach" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_inline.arn
}

# Glue role
data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service" identifiers = ["glue.amazonaws.com"] }
  }
}
resource "aws_iam_role" "glue_role" {
  name               = "${local.name_prefix}-glue-role"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
  tags               = local.tags
}
resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}
resource "aws_iam_role_policy" "glue_s3" {
  name = "${local.name_prefix}-glue-s3"
  role = aws_iam_role.glue_role.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = ["s3:GetObject","s3:PutObject","s3:ListBucket"],
      Resource = [
        aws_s3_bucket.raw.arn, "${aws_s3_bucket.raw.arn}/*",
        aws_s3_bucket.processed.arn, "${aws_s3_bucket.processed.arn}/*"
      ]
    }]
  })
}
