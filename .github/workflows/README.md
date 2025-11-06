# CI/CD (GitHub Actions)

> Back: [root](../../README.md)

Workflow: [`deploy.yml`](deploy.yml)  
- Packages Lambda functions  
- Configures AWS via OIDC  
- Runs `terraform init` + `terraform apply`

### Required repo secrets

Set in **Settings → Secrets and variables → Actions**:

| Secret name            | Purpose                                |
|------------------------|----------------------------------------|
| `AWS_ROLE_TO_ASSUME`   | IAM role ARN trusted for GitHub OIDC   |
| `TF_PROJECT_NAME`      | Terraform var `project_name`           |
| `TF_OWNER_TAG`         | Terraform var `owner_tag`              |
| `TF_FYERS_CLIENT_ID`   | Terraform var `fyers_client_id` (**secret**) |
| `TF_FYERS_SECRET_KEY`  | Terraform var `fyers_secret_key` (**secret**) |
| `TF_REDIRECT_URL`      | Terraform var `redirect_url`           |

The workflow exports them as `TF_VAR_*` so Terraform receives the values.

Return to: [root](../../README.md)
