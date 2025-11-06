#!/usr/bin/env python3
"""
aggregate_job.py (v3 - Dynamic Date)

A Spark-native AWS Glue job to aggregate 1-minute OHLCV JSON data into
multi-timeframe Parquet datasets (1m, 5m, 15m, 1d), partitioned for
efficient querying by services like Amazon Athena.

This version reads from the base S3 path and uses Spark's built-in
partition discovery and filtering for robust error handling.

It automatically calculates the date to process based on the 'Asia/Kolkata'
timezone, removing the need for a --DATE parameter.

Usage in AWS Glue:
- Job type: Spark
- Glue version: 3.0 or 4.0
- Job parameters (pass these as arguments to the job):
  --INPUT_PREFIX: Base S3 path for raw data (e.g., s3://ohlcv-pipeline/ohlcv/raw/)
  --OUTPUT_PREFIX: Base S3 path for processed data (e.g., s3://ohlcv-pipeline/processed/)
"""
import sys
import datetime
import pytz  # Required for timezone-aware dates
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, explode, from_unixtime, floor, lit, size, row_number,
    year, month, dayofmonth, lpad
)
from pyspark.sql.window import Window
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, ArrayType, DoubleType, LongType
)
from awsglue.utils import getResolvedOptions

# --- 1. Get Job Parameters & Calculate Date ---
# We removed 'DATE' from the parameters
args = getResolvedOptions(sys.argv, ['INPUT_PREFIX', 'OUTPUT_PREFIX'])
INPUT_PREFIX = args['INPUT_PREFIX'].rstrip('/')
OUTPUT_PREFIX = args['OUTPUT_PREFIX'].rstrip('/')

# --- DYNAMIC DATE CALCULATION ---
# Get the current time in India's timezone
ist_timezone = pytz.timezone('Asia/Kolkata')
current_time_ist = datetime.datetime.now(ist_timezone)

# By default, process "today's" date (IST)
DATE = current_time_ist.strftime('%Y-%m-%d')

# --- (Safer Alternative) Process "yesterday's" date ---
# Uncomment this line if your job runs early in the morning (e.g., 2 AM)
# to process the *previous* day's data.
#
# yesterday_ist = current_time_ist - datetime.timedelta(days=1)
# DATE = yesterday_ist.strftime('%Y-%m-%d')
# ---

# Parse date for input path
try:
    y, m, d = DATE.split('-')
except ValueError:
    print(f"Error: Calculated DATE '{DATE}' is not in YYYY-MM-DD format.")
    sys.exit(1)

print(f"Starting aggregation for dynamically calculated DATE={DATE}")
print(f"INPUT_PREFIX={INPUT_PREFIX}")
print(f"OUTPUT_PREFIX={OUTPUT_PREFIX}")

# --- 2. Initialize Spark Session ---
spark = SparkSession.builder \
    .appName(f"OHLCV-Aggregator-{DATE}") \
    .getOrCreate()

spark.conf.set("spark.sql.parquet.compression.codec", "snappy")
spark.conf.set("spark.sql.shuffle.partitions", "200")

# --- 3. Define Schema ---
candle_schema = ArrayType(DoubleType())
schema = StructType([
    StructField("fyers_response", StructType([
        StructField("candles", ArrayType(candle_schema))
    ]))
])

# --- 4. Read All Data in One Command ---
input_path = INPUT_PREFIX
print(f"Reading from base path: {input_path}")

# Filter for the dynamically calculated date
df_raw = spark.read \
    .schema(schema) \
    .option("multiLine", "true") \
    .json(input_path) \
    .where(
        (col("year") == y) &
        (col("month") == m) &
        (col("day") == d)
    )

print(f"Found and loaded data for {y}-{m}-{d}")

# --- 5. Explode, Flatten, and Clean Data ---
df_exploded = df_raw \
    .filter(col("fyers_response.candles").isNotNull() & (size(col("fyers_response.candles")) > 0)) \
    .select(
        col("symbol"),
        col("exchange"),
        explode(col("fyers_response.candles")).alias("candle")
    )

df_1m_base = df_exploded \
    .filter(size(col("candle")) >= 6) \
    .select(
        col("symbol"),
        col("exchange"),
        col("candle").getItem(0).cast(LongType()).alias("ts"),
        col("candle").getItem(1).cast(DoubleType()).alias("open"),
        col("candle").getItem(2).cast(DoubleType()).alias("high"),
        col("candle").getItem(3).cast(DoubleType()).alias("low"),
        col("candle").getItem(4).cast(DoubleType()).alias("close"),
        col("candle").getItem(5).cast(DoubleType()).alias("volume")
    ) \
    .withColumn("ts_ts", from_unixtime(col("ts")).cast("timestamp")) \
    .dropDuplicates(["symbol", "ts"])

df_1m_base.cache()
count = df_1m_base.count()
print(f"Base 1-minute data loaded and cached. Count: {count}")

if count == 0:
    print("No data found for the specified date. Exiting.")
    sys.exit(0)
    
# --- 6. Aggregation Logic ---
def resample_to_interval(df_input, interval_seconds, label):
    """
    Resamples 1-minute OHLCV data to a specified interval (e.g., 5m, 15m, 1d).
    """
    df_i = df_input.withColumn(
        "interval_start_epoch",
        (floor(col("ts") / interval_seconds) * interval_seconds).cast("long")
    )
    df_i = df_i.withColumn("interval_start", from_unixtime(col("interval_start_epoch")).cast("timestamp"))

    w_asc = Window.partitionBy("symbol", "exchange", "interval_start_epoch").orderBy("ts")
    w_desc = Window.partitionBy("symbol", "exchange", "interval_start_epoch").orderBy(col("ts").desc())

    opens = df_i.withColumn("rn", row_number().over(w_asc)) \
                .filter(col("rn") == 1) \
                .select("symbol", "exchange", "interval_start", "interval_start_epoch", col("open").alias("open"))

    closes = df_i.withColumn("rn", row_number().over(w_desc)) \
                 .filter(col("rn") == 1) \
                 .select("symbol", "exchange", "interval_start", "interval_start_epoch", col("close").alias("close"))

    aggs = df_i.groupBy("symbol", "exchange", "interval_start", "interval_start_epoch") \
               .agg(
                   F.max("high").alias("high"),
                   F.min("low").alias("low"),
                   F.sum("volume").alias("volume")
               )

    out = aggs.join(opens, ["symbol", "exchange", "interval_start", "interval_start_epoch"], "left") \
              .join(closes, ["symbol", "exchange", "interval_start", "interval_start_epoch"], "left") \
              .withColumn("timeframe", lit(label)) \
              .withColumn("year", year(col("interval_start"))) \
              .withColumn("month", lpad(month(col("interval_start")).cast("string"), 2, "0")) \
              .withColumn("day", lpad(dayofmonth(col("interval_start")).cast("string"), 2, "0"))

    return out.select(
        "symbol", "exchange", "timeframe", "interval_start", "interval_start_epoch",
        "year", "month", "day", "open", "high", "low", "close", "volume"
    )

# --- 7. Generate All Timeframes and Union Them ---
intervals = [
    ("1m", 60),
    ("5m", 300),
    ("15m", 900),
    ("1d", 86400) # 60 * 60 * 24
]

df_all_aggs = None

for label, secs in intervals:
    print(f"Calculating timeframe: {label}...")
    df_agg = resample_to_interval(df_1m_base, secs, label)
    
    if df_all_aggs is None:
        df_all_aggs = df_agg
    else:
        df_all_aggs = df_all_aggs.unionByName(df_agg)

# --- 8. Write Output ---
output_path = f"{OUTPUT_PREFIX}/"
partition_cols = ["timeframe", "exchange", "symbol", "year", "month", "day"]

print(f"Writing aggregated data to: {output_path}")
df_all_aggs.write \
    .mode("overwrite") \
    .partitionBy(*partition_cols) \
    .parquet(output_path)

# Clear the cache
df_1m_base.unpersist()
print("Aggregation job completed successfully.")