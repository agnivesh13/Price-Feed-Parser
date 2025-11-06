#!/usr/bin/env python3
"""
ingest_async_with_retries.py (Lambda-ready, with token refresh)

- Expects Secrets Manager secret containing JSON:
  { "access_token": "...", "client_id":"...", "refresh_token":"...", "app_secret":"..." }

- Important env variables:
  S3_BUCKET, TICKER_S3_PATH, FYERS_SECRET_NAME, AWS_REGION
  Optional: FYERS_HISTORY_URL (default uses api-t1 /data/history)
"""

import os
import asyncio
import time
import json
import random
import traceback
import hashlib
from datetime import datetime, timezone
from typing import Optional
import aiohttp
import boto3
from botocore.exceptions import ClientError

# ---------- Config / env ----------
S3_BUCKET = os.environ["S3_BUCKET"]
TICKER_S3_PATH = os.environ["TICKER_S3_PATH"]
FYERS_SECRET_NAME = os.environ.get("FYERS_SECRET_NAME", "fyers/credentials")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
# Use the working endpoint base used by your friend's code
FYERS_HISTORY_URL = os.environ.get("FYERS_HISTORY_URL", "https://api-t1.fyers.in/data/history")
FYERS_REFRESH_URL = os.environ.get("FYERS_REFRESH_URL", "https://api-t1.fyers.in/api/v3/validate-refresh-token")

MAX_PER_SEC = int(os.environ.get("MAX_PER_SEC", "9"))
MAX_PER_MIN = int(os.environ.get("MAX_PER_MIN", "180"))
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "6"))
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "5"))

DLQ_PREFIX = os.environ.get("DLQ_PREFIX", "ohlcv/errors/")
RAW_PREFIX = os.environ.get("RAW_PREFIX", "ohlcv/raw/")
ENABLE_CLOUDWATCH = os.environ.get("ENABLE_CLOUDWATCH", "0") == "1"
CW_NAMESPACE = os.environ.get("CW_NAMESPACE", "PriceFeedParser/Ingest")
INGEST_TAGS = os.environ.get("INGEST_TAGS", "")

# ---------- AWS clients ----------
boto_session = boto3.session.Session(region_name=AWS_REGION)
s3 = boto_session.client("s3")
sm = boto_session.client("secretsmanager")
cw = boto_session.client("cloudwatch") if ENABLE_CLOUDWATCH else None

# ---------- Shared credentials & locks ----------
# CREDENTIALS is populated from Secrets Manager and updated on refresh.
CREDENTIALS = {}
refresh_lock = asyncio.Lock()

# ---------- Utils ----------
def now_iso_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def s3_key_for_raw(symbol: str, ingest_ts_iso: str):
    yyyy, mm, dd = ingest_ts_iso.split("T")[0].split("-")
    # sanitize symbol for safe S3 key (replace ":" with "_")
    sym_key = symbol.replace(":", "_").replace("/", "_")
    return f"{RAW_PREFIX}symbol={sym_key}/exchange=NSE/year={yyyy}/month={mm}/day={dd}/ingest-{ingest_ts_iso}.json"

def s3_key_for_dlq(symbol: str, ingest_ts_iso: str):
    yyyy, mm, dd = ingest_ts_iso.split("T")[0].split("-")
    sym_key = symbol.replace(":", "_").replace("/", "_")
    return f"{DLQ_PREFIX}symbol={sym_key}/year={yyyy}/month={mm}/day/{dd}/failed-{ingest_ts_iso}.json"

def put_metric(name: str, value: float, unit: str = "Count", dimensions: Optional[list] = None):
    if not ENABLE_CLOUDWATCH or cw is None:
        return
    try:
        dims = dimensions or []
        cw.put_metric_data(Namespace=CW_NAMESPACE, MetricData=[{
            "MetricName": name,
            "Timestamp": datetime.utcnow(),
            "Value": value,
            "Unit": unit,
            "Dimensions": dims,
        }])
    except Exception as e:
        print("Warning: failed to publish metric:", e)

# ---------- Token bucket (async-friendly) ----------
class AsyncTokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float):
        self.rate = float(rate_per_sec)
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def consume(self, amount: float = 1.0):
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.last
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last = now
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                needed = amount - self.tokens
                wait = needed / self.rate
            await asyncio.sleep(wait + 0.001)

# ---------- Secrets / tickers load ----------
def load_secret_into_credentials():
    """
    Loads the Secrets Manager secret into the global CREDENTIALS dict.
    SecretString must be JSON with keys like access_token, client_id, refresh_token, app_secret
    """
    global CREDENTIALS
    resp = sm.get_secret_value(SecretId=FYERS_SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    # ensure keys present (they may not all exist)
    CREDENTIALS = {
        "access_token": secret.get("access_token"),
        "client_id": secret.get("client_id") or os.environ.get("FYERS_CLIENT_ID"),
        "refresh_token": secret.get("refresh_token"),
        "app_secret": secret.get("app_secret")
    }
    return CREDENTIALS

def update_secret_access_token(new_token: str):
    """
    Overwrite the access_token in the existing secret in Secrets Manager.
    This keeps other fields intact if present.
    """
    try:
        # fetch existing secret to preserve other fields
        resp = sm.get_secret_value(SecretId=FYERS_SECRET_NAME)
        secret = json.loads(resp["SecretString"])
        secret["access_token"] = new_token
        sm.update_secret(SecretId=FYERS_SECRET_NAME, SecretString=json.dumps(secret))
        print("Updated access_token in Secrets Manager.")
    except Exception as e:
        print("Warning: failed to update secret in Secrets Manager:", e)

def load_tickers_from_s3(s3_path: str):
    parts = s3_path.split("/", 3)
    if len(parts) < 4 or not s3_path.startswith("s3://"):
        raise ValueError("TICKER_S3_PATH must be in form s3://bucket/key")
    bucket = parts[2]
    key = parts[3]
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read().decode("utf-8")
    tickers = [line.strip() for line in body.splitlines() if line.strip()]
    return tickers

# ---------- S3 writes ----------
def s3_put_raw(key: str, payload: dict, metadata: Optional[dict] = None):
    body = json.dumps(payload).encode("utf-8")
    meta = metadata or {}
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, Metadata=meta)
    except ClientError as e:
        print("S3 put_object failed:", e)
        raise

def s3_put_dlq(key: str, payload: dict, metadata: Optional[dict] = None):
    body = json.dumps(payload, indent=2).encode("utf-8")
    meta = metadata or {}
    meta.setdefault("dlq_reason", "unknown")
    try:
        s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body, Metadata=meta)
    except ClientError as e:
        print("S3 put_object DLQ failed:", e)
        raise

# ---------- Token refresh (async) ----------
async def refresh_access_token_async(session: aiohttp.ClientSession):
    """
    Refresh access token using credentials in CREDENTIALS.
    Uses refresh_lock to ensure single concurrent refresh across tasks.
    Returns new token or None.
    """
    global CREDENTIALS
    async with refresh_lock:
        # double-check: maybe another task refreshed while we waited
        if CREDENTIALS.get("access_token"):
            # optionally test validity? We'll just proceed to refresh only if refresh fields exist
            pass

        client_id = CREDENTIALS.get("client_id")
        refresh_token = CREDENTIALS.get("refresh_token")
        app_secret = CREDENTIALS.get("app_secret")
        if not (client_id and refresh_token and app_secret):
            print("Cannot refresh token: missing client_id / refresh_token / app_secret in secret.")
            return None

        app_id_hash = hashlib.sha256(f"{client_id}:{app_secret}".encode()).hexdigest()
        payload = {
            "grant_type": "refresh_token",
            "appIdHash": app_id_hash,
            "refresh_token": refresh_token
        }
        headers = {"Content-Type": "application/json"}
        try:
            async with session.post(FYERS_REFRESH_URL, json=payload, headers=headers, timeout=30) as resp:
                text = await resp.text()
                if resp.status != 200:
                    print(f"Refresh token HTTP error {resp.status}: {text}")
                    return None
                data = await resp.json()
                # expected shape similar to friend code: s == 'ok' and contains access_token
                if isinstance(data, dict) and data.get("s") == "ok" and data.get("access_token"):
                    new_token = data["access_token"]
                    # update in-memory and persist to Secrets Manager (best-effort)
                    CREDENTIALS["access_token"] = new_token
                    try:
                        update_secret_access_token(new_token)
                    except Exception as e:
                        print("Warning: failed to persist refreshed token to Secrets Manager:", e)
                    print("Refreshed access token successfully.")
                    return new_token
                else:
                    print("Refresh token response not OK:", data)
                    return None
        except Exception as e:
            print("Exception while refreshing token:", e)
            return None

# ---------- Fetch worker (uses CREDENTIALS) ----------
async def fetch_one(
    session: aiohttp.ClientSession,
    symbol: str,
    ingest_ts_iso: str,
    date_str: str,
    sem: asyncio.Semaphore,
    tb_sec: AsyncTokenBucket,
    tb_min: AsyncTokenBucket
):
    attempt = 0
    backoff_base = float(os.environ.get("BACKOFF_BASE", "2.0"))

    # params exactly like your working local script
    params = {
        "symbol": symbol,
        "resolution": "1",
        "date_format": "1",
        "range_from": date_str,
        "range_to": date_str,
        "cont_flag": "1"
    }

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        await tb_min.consume(1.0)
        await tb_sec.consume(1.0)
        async with sem:
            try:
                # Build headers using current credentials (client_id:access_token)
                client_id = CREDENTIALS.get("client_id")
                access_token = CREDENTIALS.get("access_token")
                if not client_id or not access_token:
                    print(f"[{symbol}] Missing client_id or access_token in CREDENTIALS.")
                    # attempt to refresh aggressively if possible
                    if CREDENTIALS.get("refresh_token"):
                        print(f"[{symbol}] Attempting immediate refresh due to missing token...")
                        await refresh_access_token_async(session)
                        client_id = CREDENTIALS.get("client_id")
                        access_token = CREDENTIALS.get("access_token")
                    if not client_id or not access_token:
                        return (symbol, False, attempt, None, "missing_credentials")

                headers = {
                    "Authorization": f"{client_id}:{access_token}",  # <-- important: client_id:access_token
                    "Content-Type": "application/json",
                    "version": "3",
                    "User-Agent": "price-feed-parser/1.0"
                }

                timeout = aiohttp.ClientTimeout(total=30)
                async with session.get(FYERS_HISTORY_URL, headers=headers, params=params, timeout=timeout) as resp:
                    status = resp.status
                    text = await resp.text()
                    headers_snippet = {k: resp.headers.get(k) for k in ("Retry-After", "Content-Type") if resp.headers.get(k)}

                    if status == 200:
                        # parse JSON if possible
                        try:
                            data = await resp.json()
                        except Exception:
                            data = {"raw_text": text}

                        # FYERS sometimes returns 200 with s == 'error' for auth problems
                        if isinstance(data, dict) and data.get("s") == "error":
                            msg = (data.get("message") or "").lower()
                            print(f"[{symbol}] Fyers API error (status 200): {data.get('message')!r}")
                            # if message hints at auth token problems -> try refresh (only once)
                            if ("auth" in msg or "token" in msg or "authenticate" in msg) and CREDENTIALS.get("refresh_token"):
                                print(f"[{symbol}] Authentication error detected in 200 response; attempting refresh...")
                                new_token = await refresh_access_token_async(session)
                                if new_token:
                                    print(f"[{symbol}] Refreshed token; retrying immediately (attempt {attempt}/{MAX_ATTEMPTS}).")
                                    # small sleep to let new token propagate
                                    await asyncio.sleep(0.5)
                                    continue  # retry the request with refreshed token
                                else:
                                    print(f"[{symbol}] Token refresh failed; aborting this symbol.")
                                    break
                            # otherwise treat as non-auth error and retry/backoff a few times
                            wait = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.2
                            await asyncio.sleep(wait)
                            continue

                        # success path
                        key = s3_key_for_raw(symbol, ingest_ts_iso)
                        metadata = {"ingest_ts": ingest_ts_iso, "symbol": symbol, "ingest_tags": INGEST_TAGS}
                        s3_put_raw(key, {"fyers_response": data}, metadata=metadata)
                        put_metric("IngestSuccess", 1, dimensions=[{"Name": "Symbol", "Value": symbol}])
                        return (symbol, True, attempt, status, None)

                    # 429 handling
                    if status == 429:
                        retry_after = None
                        if "Retry-After" in resp.headers:
                            try:
                                retry_after = float(resp.headers["Retry-After"])
                            except:
                                retry_after = None
                        wait = retry_after if retry_after else (backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5)
                        print(f"[{symbol}] 429 rate-limited. headers={headers_snippet} attempt {attempt}/{MAX_ATTEMPTS}. waiting {wait:.2f}s")
                        await asyncio.sleep(wait)
                        continue

                    # 5xx
                    if 500 <= status < 600:
                        retry_after = None
                        if "Retry-After" in resp.headers:
                            try:
                                retry_after = float(resp.headers["Retry-After"])
                            except:
                                retry_after = None
                        wait = retry_after if retry_after else (backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5)
                        print(f"[{symbol}] Server error {status}. headers={headers_snippet} body_preview={text[:800]!r}. attempt {attempt}/{MAX_ATTEMPTS}. waiting {wait:.2f}s")
                        await asyncio.sleep(wait)
                        continue

                    # Auth errors 401/403
                    if status in (401, 403):
                        print(f"[{symbol}] HTTP auth error {status}. Attempting refresh if possible.")
                        if CREDENTIALS.get("refresh_token"):
                            new_token = await refresh_access_token_async(session)
                            if new_token:
                                print(f"[{symbol}] Token refreshed after HTTP {status}; retrying.")
                                await asyncio.sleep(0.5)
                                continue
                        # otherwise treat as permanent auth failure
                        print(f"[{symbol}] Auth error and no refresh available; aborting.")
                        break

                    # Other client errors
                    print(f"[{symbol}] Unexpected client error {status}. headers={headers_snippet} body_preview={text[:400]!r}")
                    wait = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.2
                    await asyncio.sleep(wait)
                    continue

            except asyncio.TimeoutError:
                wait = backoff_base * (2 ** (attempt - 1)) + random.random() * 0.5
                print(f"[{symbol}] Timeout on attempt {attempt}. waiting {wait:.2f}s")
                await asyncio.sleep(wait)
                continue
            except Exception as e:
                tb = traceback.format_exc()
                print(f"[{symbol}] Exception on attempt {attempt}: {e}\n{tb}")
                wait = backoff_base * (2 ** (attempt - 1)) + random.random()
                await asyncio.sleep(wait)
                continue

    # exhausted or permanent failure
    err_info = f"Exhausted {MAX_ATTEMPTS} attempts"
    print(f"[{symbol}] failed after {MAX_ATTEMPTS} attempts")
    put_metric("IngestFailed", 1, dimensions=[{"Name": "Symbol", "Value": symbol}])
    dlq_key = s3_key_for_dlq(symbol, ingest_ts_iso)
    payload = {
        "symbol": symbol,
        "failed_at": now_iso_utc(),
        "attempts": attempt,
        "note": err_info,
        "params_sent": params
    }
    s3_put_dlq(dlq_key, payload, metadata={"symbol": symbol, "ingest_ts": ingest_ts_iso, "dlq_reason": err_info})
    return (symbol, False, attempt, None, err_info)


# ---------- Main run_once ----------
async def run_once():
    # load tickers & credentials
    tickers = load_tickers_from_s3(TICKER_S3_PATH)
    load_secret_into_credentials()
    if not CREDENTIALS.get("access_token"):
        print("Warning: no access_token in secret; you may need to refresh manually or provide refresh credentials.")

    ingest_ts_iso = now_iso_utc()
    current_date_str = ingest_ts_iso.split("T")[0]

    print(f"Starting ingest run for {len(tickers)} tickers at {ingest_ts_iso} (fetching for date: {current_date_str})")

    # token buckets: sec and minute
    tb_sec = AsyncTokenBucket(rate_per_sec=MAX_PER_SEC, capacity=MAX_PER_SEC)
    tb_min = AsyncTokenBucket(rate_per_sec=(MAX_PER_MIN / 60.0), capacity=MAX_PER_MIN)

    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    results = []
    connector = aiohttp.TCPConnector(limit=MAX_CONCURRENCY * 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            asyncio.create_task(
                fetch_one(session, sym, ingest_ts_iso, current_date_str, sem, tb_sec, tb_min)
            ) for sym in tickers
        ]

        for coro in asyncio.as_completed(tasks):
            try:
                res = await coro
                results.append(res)
            except Exception as e:
                print("Unhandled exception in task:", e)
                results.append((None, False, 0, None, str(e)))

    success = sum(1 for r in results if r[1] is True)
    failed = len(results) - success
    print(f"Ingest complete: {success} success, {failed} failed")

    put_metric("IngestRunSuccessCount", success)
    put_metric("IngestRunFailedCount", failed)
    put_metric("IngestRunSymbolsTotal", len(tickers))

    return {"success": success, "failed": failed, "total": len(tickers)}

# ---------- Lambda Handler ----------
def lambda_handler(event, context):
    print("Starting ingest run...")
    try:
        result = asyncio.run(run_once())
        print("Ingest run complete:", result)
        if result.get("failed", 0) > 0:
            raise Exception(f"{result['failed']} symbols failed to ingest.")
        return {'statusCode': 200, 'body': json.dumps(result)}
    except Exception as e:
        print(f"Error in handler: {str(e)}")
        raise e

# ---------- CLI ----------
def main():
    res = asyncio.run(run_once())
    if res["failed"] > 0:
        exit(2)
    exit(0)

if __name__ == "__main__":
    main()
