# Lambda Layers (optional)

> Back: [root](../README.md)

This folder may contain a prebuilt layer (e.g., `aiohttp`, `yarl`, `multidict`) to keep deployment zips small.

If you want to use it:
1. Upload `aio-layer.zip` as a Lambda Layer in your account.
2. Add the layer ARN to the ingest Lambda in Terraform:
   ```hcl
   resource "aws_lambda_function" "ingest" {
     # ...
     layers = ["arn:aws:lambda:ap-south-1:<account-id>:layer:aio-layer:<version>"]
   }
