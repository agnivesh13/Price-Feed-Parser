# Terraform (infra)

This module provisions:
- S3 buckets: **raw**, **processed**, **config**
- Secrets Manager secret for Fyers tokens
- IAM roles/policies (Lambdas, Glue)
- API Gateway + OAuth Lambda
- Ingest Lambda + EventBridge schedule
- Glue Job for aggregation

> Back to root: [README.md](../../README.md)

---

## Variables

Declared in [`variables.tf`](variables.tf). Primary inputs:

| Name                 | Type   | Notes |
|----------------------|--------|------|
| `project_name`       | string | Prefix for resources (e.g., `ohlcv-price-pipeline`) |
| `aws_region`         | string | Default `ap-south-1` |
| `owner_tag`          | string | Tagging |
| `fyers_client_id`    | string | **Secret** – pass via GitHub Actions secrets |
| `fyers_secret_key`   | string | **Secret** – pass via GitHub Actions secrets |
| `redirect_url`       | string | API GW callback URL |
| `ingest_schedule_cron` | string | Default: `cron(0/30 3-9 ? * MON-FRI *)` |

If running locally (without CI), create `terraform.tfvars` (non-secret values only):

```hcl
project_name  = "ohlcv-price-pipeline"
aws_region    = "ap-south-1"
owner_tag     = "yourname"
# Prefer to pass secrets via environment or TF_VAR_*
