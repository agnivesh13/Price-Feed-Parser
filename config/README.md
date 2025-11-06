# Config & environment

> Back: [root](../README.md)

- `sample.env` – **local-only** example of environment variables.  
  Copy to `.env` if you experiment locally (never commit secrets).

In production, values are **injected by Terraform/CI** into:
- Lambda environment variables,
- Glue default arguments,
- Terraform variables (via GitHub secrets).

Secrets (Fyers client/app secret, access/refresh tokens) live in **AWS Secrets Manager**.

Return to: [root](../README.md)
