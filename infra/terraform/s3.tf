resource "aws_s3_bucket" "raw" {
  bucket = "${local.name_prefix}-raw"
  tags   = local.tags
}

resource "aws_s3_bucket" "processed" {
  bucket = "${local.name_prefix}-processed"
  tags   = local.tags
}

resource "aws_s3_bucket" "config" {
  bucket = "${local.name_prefix}-config"
  tags   = local.tags
}

# Optional: lifecycle, encryption, versioning
resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_versioning" "processed" {
  bucket = aws_s3_bucket.processed.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_versioning" "config" {
  bucket = aws_s3_bucket.config.id
  versioning_configuration { status = "Enabled" }
}
