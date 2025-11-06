
---

## 7) `ticker_list/README.md`

```markdown
# Ticker list

> Back: [root](../README.md)

Source of truth for symbols. Example: `nse_tickers.csv`

### Format
- One symbol per line, any of:

NSE:RELIANCE-EQ
NSE:TCS-EQ
NSE:HDFCBANK-EQ


- CSV is fine; the ingest Lambda just needs a **flat list** once uploaded to S3.

### Upload path
Upload to the **config bucket** created by Terraform:
s3://<project>-config/tickers/tickers.txt


> The ingest Lambda reads `TICKER_S3_PATH`, set in Terraform. Adjust the key there if you change the filename.

Return to: [root](../README.md)
