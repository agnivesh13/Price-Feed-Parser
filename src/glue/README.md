# Glue job: `aggregate_job.py`

> Back: [root](../../README.md) • Lambdas: [src/lambda](../lambda/README.md) • Infra: [terraform](../../infra/terraform/README.md)

This Spark job:
- Reads raw JSON under `--INPUT_PREFIX` (whole base path),
- Filters partitions for IST **today**,
- Explodes candle arrays, dedupes (`symbol`, `ts`),
- Resamples to `1m`, `5m`, `15m`, `1d`,
- Writes Parquet to `--OUTPUT_PREFIX` with partitions:
  `timeframe`, `exchange`, `symbol`, `year`, `month`, `day`.

### Arguments (Terraform `default_arguments`)

- `--INPUT_PREFIX`  e.g., `s3://<raw-bucket>/ohlcv/raw/`
- `--OUTPUT_PREFIX` e.g., `s3://<processed-bucket>/processed/`

> If you schedule Glue early morning, you can switch to “yesterday” in the code (lines are present and commented).

### Partitions (output)
- `timeframe=1m|5m|15m|1d`
- `exchange=NSE`
- `symbol=NSE_<SYMBOL>-EQ`
- `year`, `month`, `day`

Query easily from Athena after creating a table or running a crawler.

Return to: [root](../../README.md)
