# Price Feed Parser (AWS + Fyers) 

[![Deploy](https://img.shields.io/badge/CI-CD-blue)](.github/workflows/deploy.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

End-to-end data pipeline that:
- authenticates with **Fyers** via OAuth2 (API Gateway + Lambda),
- **ingests** 1-minute OHLCV history into S3 (async Lambda with rate limiting),
- **aggregates** raw JSON into Parquet timeframes (Glue: `1m`, `5m`, `15m`, `1d`),
- writes Athena-friendly **partitions**.

> 🔗 Quick links:  
> • Infra: [`infra/terraform`](infra/terraform/README.md)  
> • Lambdas: [`src/lambda`](src/lambda/README.md)  
> • Glue: [`src/glue`](src/glue/README.md)  
> • Config & env: [`config`](config/README.md)  
> • Ticker list: [`ticker_list`](ticker_list/README.md)  
> • CI/CD: [`.github/workflows`](.github/workflows/README.md)  
> • MIT License: [`LICENSE`](LICENSE)

---

## Architecture
┌─────────────┐ GET /oauth/callback ┌──────────────┐
│ Browser ├──────────────────────────▶│ API Gateway │
└─────────────┘ └──────┬───────┘
│ (AWS_PROXY)
┌─────▼──────┐
│ OAuth Lmda │──┐
└─────┬──────┘ │ exchange auth_code
│ │ store tokens
Secrets Manager ◀─┘
│
┌──────────────────────┴─────────────────────┐
│ Ingest Lambda (async, aiohttp) │
EventBridge (schedule) ─┤ • reads tickers from S3 (config) │
│ • rate limits + retries + refresh │
└───────────┬────────────────────────────────┘
│ raw JSON
┌──▼────────────────────────────────────┐
│ S3 (raw bucket) │
│ ohlcv/raw/… & ohlcv/errors/… │
└──┬───────────────────────────────────┬─┘
│ │
│ Glue Job │
│ (daily IST, dynamic date) │
▼ │
┌──────────────────────┐ │
│ S3 (processed) │◀────────────────────┘
│ parquet partitions │
└──────────────────────┘


### S3 path conventions

**Raw:**  
`s3://<raw-bucket>/ohlcv/raw/symbol=<SYM>/exchange=<EXCH>/year=YYYY/month=MM/day=DD/ingest-<ISO>.json`

**DLQ:**  
`s3://<raw-bucket>/ohlcv/errors/symbol=<SYM>/year=YYYY/month=MM/day/DD/failed-<ISO>.json`

**Processed:**  
`s3://<processed-bucket>/processed/timeframe=<1m|5m|15m|1d>/exchange=<EXCH>/symbol=<SYM>/year=YYYY/month=MM/day=DD/part-*.parquet`

---

## What’s in this repo

.
├─ .github/workflows/deploy.yml # CI/CD (Terraform deploy)
├─ config/
│ └─ sample.env # local-only example env (don’t commit secrets)
├─ infra/terraform/ # IaC (S3, Secrets, IAM, API GW, Lambdas, Glue, Events)
│ ├─ *.tf
│ └─ README.md
├─ lambda_layers/
│ ├─ aio-layer.zip # optional Lambda layer for aiohttp (if you prefer)
│ └─ README.md
├─ src/
│ ├─ glue/aggregate_job.py # Glue ETL (1m->5m/15m/1d)
│ └─ lambda/
│ ├─ callback_handler.py # OAuth Gateway handler
│ └─ ingest_lambda.py # Async ingest with retries & refresh
│ └─ README.md
├─ ticker_list/
│ └─ nse_tickers.csv # your tickers (source of truth)
├─ .gitignore
├─ LICENSE
└─ README.md


---

## How it works (high-level)

1. **OAuth**: Hit the API Gateway URL. It redirects to Fyers; after login, the Lambda exchanges `auth_code` → `access_token` + `refresh_token` and persists both in **AWS Secrets Manager**.
2. **Ingestion**: EventBridge triggers the ingest Lambda on a schedule. It loads **tickers** from S3, calls Fyers history API with built-in rate limiting, and writes **raw JSON** (DLQ on failures).
3. **Aggregation**: A Glue job reads `raw/` for IST **today**, explodes candles, resamples to `5m/15m/1d`, and writes **Parquet partitions** under `processed/`.

---

## Quick start (production)

1) **Set GitHub repo secrets** (used by CI): see [`.github/workflows/README.md`](.github/workflows/README.md)  
2) **Push to `main`** → CI builds & applies Terraform.  
3) From Terraform **outputs**, open the `oauth_authorize_url` and complete Fyers login.  
4) Put your tickers file at S3 path from [ticker_list/README](ticker_list/README.md).  
5) Verify ingestion logs and processed Parquet in S3.

---

## Local testing (optional)

- Duplicate `config/sample.env` → `.env` (not committed).  
- You can unit test your handlers locally (e.g., `pytest`), but infra deploys via Terraform/CI.

---

## Troubleshooting

- **Tokens not found**: ensure you completed OAuth at the Gateway URL; check Secrets Manager JSON has `access_token`.
- **429 / rate limits**: tune `MAX_PER_SEC`, `MAX_PER_MIN` in Terraform env for the ingest Lambda.
- **No processed data**: confirm raw exists for IST date; Glue job uses **IST today** by default.
- **Ticker file missing**: confirm `TICKER_S3_PATH` env and that the object exists.

---

## License

This project is licensed under the **MIT License**. See [`LICENSE`](LICENSE).
