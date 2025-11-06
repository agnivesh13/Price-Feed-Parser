#!/usr/bin/env bash
set -euo pipefail
: "${GLUE_S3_BUCKET:?Set GLUE_S3_BUCKET}"
: "${AWS_REGION:=ap-south-1}"
aws s3 cp glue/corrected_aggregate_job.py "s3://${GLUE_S3_BUCKET}/glue-scripts/corrected_aggregate_job.py" --region "$AWS_REGION"
