#!/usr/bin/env python3
#this is Version 5 agg + IST time + yesterday's safe write
"""
corrected_aggregate_job.py (v5 - IST-aware timestamps & safe writes)

Key changes:
- Convert epoch (ts) -> timestamp in IST using from_utc_timestamp(...)
- For 1d timeframe, align day-buckets to IST midnight (offset 19800 seconds)
- Derive year/month/day from IST interval_start so partitions match DATE (IST)
- Use dynamic partition overwrite and write only today's partitions
"""

import sys
import datetime
import pytz
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, explode, from_unixtime, floor, lit, size, row_number,
    year, month, dayofmonth, lpad, from_utc_timestamp
)
from pyspark.sql.window import Window
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, ArrayType, DoubleType, LongType
)
from awsglue.utils import getResolvedOptions

# ------------------------------------------------------------
# 1. Parameters & Dynamic IST Date
# ------------------------------------------------------------
args = getResolvedOptions(sys.argv, ['INPUT_PREFIX', 'OUTPUT_PREFIX'])
INPUT_PREFIX = args['INPUT_PREFIX'].rstrip('/')
OUTPUT_PREFIX = args['OUTPUT_PREFIX'].rstrip('/')

ist_timezone = pytz.timezone('Asia/Kolkata')
current_time_ist = datetime.datetime.now(ist_timezone)
DATE = current_time_ist.strftime('%Y-%m-%d')

try:
    y, m, d = DATE.split('-')
except ValueError:
    print(f"Invalid DATE format: {DATE}")
    sys.exit(1)

print(f"Processing DATE = {DATE} (Asia/Kolkata)")

# ------------------------------------------------------------
# 2. Spark Session
# ------------------------------------------------------------
spark = SparkSession.builder.appName(f"OHLCV-Aggregator-{DATE}").getOrCreate()

spark.conf.set("spark.sql.parquet.compression.codec", "snappy")
spark.conf.set("spark.sql.shuffle.partitions", "200")

# IMPORTANT: prevents old-partition deletion (only overwrite partitions present in DF)
spark.conf.set("spark.sql.sources.partitionOverwriteMode", "dynamic")

# ------------------------------------------------------------
# 3. Input Schema
# ------------------------------------------------------------
candle_schema = ArrayType(DoubleType())

schema = StructType([
    StructField("symbol", StringType()),
    StructField("exchange", StringType()),
    StructField("year", StringType()),
    StructField("month", StringType()),
    StructField("day", StringType()),
    StructField("fyers_response", StructType([
        StructField("candles", ArrayType(candle_schema))
    ]))
])

# ------------------------------------------------------------
# 4. Load Data (Spark Will Prune Partitions)
# ------------------------------------------------------------
input_path = INPUT_PREFIX

df_raw = (
    spark.read.schema(schema)
    .option("multiLine", "true")
    .json(input_path)
    .where((col("year") == y) & (col("month") == m) & (col("day") == d))
)

print("Loaded raw data rows:", df_raw.count())

# ------------------------------------------------------------
# 5. Explode Candles → 1m OHLCV
# ------------------------------------------------------------
df_exploded = (
    df_raw.filter(col("fyers_response.candles").isNotNull() & (size(col("fyers_response.candles")) > 0))
          .select("symbol", "exchange", explode("fyers_response.candles").alias("candle"))
)

df_1m_base = (
    df_exploded.filter(size(col("candle")) >= 6)
    .select(
        "symbol",
        "exchange",
        col("candle")[0].cast(LongType()).alias("ts"),     # epoch seconds (UTC epoch)
        col("candle")[1].cast(DoubleType()).alias("open"),
        col("candle")[2].cast(DoubleType()).alias("high"),
        col("candle")[3].cast(DoubleType()).alias("low"),
        col("candle")[4].cast(DoubleType()).alias("close"),
        col("candle")[5].cast(DoubleType()).alias("volume")
    )
    # convert epoch -> UTC timestamp then convert to IST timestamp
    .withColumn("ts_ts", from_utc_timestamp(from_unixtime(col("ts")).cast("timestamp"), "Asia/Kolkata"))
    .dropDuplicates(["symbol", "ts"])
)

df_1m_base.cache()
base_count = df_1m_base.count()
print("1m rows:", base_count)

if base_count == 0:
    print("No data for today. Exiting.")
    sys.exit(0)

# ------------------------------------------------------------
# Utility: IST offset seconds (5.5 hours)
# ------------------------------------------------------------
IST_OFFSET_SECONDS = 5 * 3600 + 30 * 60  # 19800

# ------------------------------------------------------------
# 6. Timeframe Aggregation Function (IST-aware)
# ------------------------------------------------------------
def resample_to_interval(df_input, interval_seconds, label):
    """
    Resample using epoch arithmetic. Convert interval_start to IST for partitioning.
    Special-case for daily (86400s) to align day boundaries to IST midnight.
    """
    if interval_seconds == 86400:
        # Align day buckets to IST midnight:
        # shift ts by IST_OFFSET, floor to day, then shift back
        interval_start_epoch_expr = ((floor((col("ts") + lit(IST_OFFSET_SECONDS)) / interval_seconds) * interval_seconds) - lit(IST_OFFSET_SECONDS)).cast("long")
    else:
        interval_start_epoch_expr = (floor(col("ts") / interval_seconds) * interval_seconds).cast("long")

    df_i = df_input.withColumn("interval_start_epoch", interval_start_epoch_expr)

    # interval_start as IST timestamp:
    df_i = df_i.withColumn(
        "interval_start",
        from_utc_timestamp(from_unixtime(col("interval_start_epoch")).cast("timestamp"), "Asia/Kolkata")
    )

    # Windows for open/close (order by raw epoch 'ts' gives correct chron order)
    w_asc = Window.partitionBy("symbol", "exchange", "interval_start_epoch").orderBy("ts")
    w_desc = Window.partitionBy("symbol", "exchange", "interval_start_epoch").orderBy(col("ts").desc())

    opens = (
        df_i.withColumn("rn", row_number().over(w_asc))
            .filter(col("rn") == 1)
            .select("symbol", "exchange", "interval_start_epoch", "interval_start", col("open").alias("open"))
    )

    closes = (
        df_i.withColumn("rn", row_number().over(w_desc))
            .filter(col("rn") == 1)
            .select("symbol", "exchange", "interval_start_epoch", "interval_start", col("close").alias("close"))
    )

    aggs = (
        df_i.groupBy("symbol", "exchange", "interval_start_epoch", "interval_start")
            .agg(
                F.max("high").alias("high"),
                F.min("low").alias("low"),
                F.sum("volume").alias("volume")
            )
    )

    result = (
        aggs.join(opens, ["symbol", "exchange", "interval_start_epoch", "interval_start"], "left")
            .join(closes, ["symbol", "exchange", "interval_start_epoch", "interval_start"], "left")
            .withColumn("timeframe", lit(label))
            .withColumn("year", year(col("interval_start")).cast("string"))
            .withColumn("month", lpad(month(col("interval_start").cast("timestamp")).cast("string"), 2, "0"))
            .withColumn("day", lpad(dayofmonth(col("interval_start")).cast("string"), 2, "0"))
    )

    return result.select(
        "symbol", "exchange", "timeframe", "interval_start", "interval_start_epoch",
        "year", "month", "day", "open", "high", "low", "close", "volume"
    )

# ------------------------------------------------------------
# 7. Build All Timeframes
# ------------------------------------------------------------
intervals = [
    ("1m", 60),
    ("5m", 300),
    ("15m", 900),
    ("1d", 86400)
]

df_all = None
for label, secs in intervals:
    print("Aggregating:", label)
    df_tf = resample_to_interval(df_1m_base, secs, label)
    df_all = df_tf if df_all is None else df_all.unionByName(df_tf)

# ------------------------------------------------------------
# 8. Write Output (SAFE & IST-partitioned)
# ------------------------------------------------------------
partition_cols = ["timeframe", "exchange", "symbol", "year", "month", "day"]
output_path = OUTPUT_PREFIX.rstrip("/") + "/"

# Normalize year/month/day strings and zero-pad
df_all = df_all \
    .withColumn("year", col("year").cast("string")) \
    .withColumn("month", lpad(col("month").cast("string"), 2, "0")) \
    .withColumn("day", lpad(col("day").cast("string"), 2, "0"))

# Filter to today's IST date (extra safety)
df_today = df_all.filter((col("year") == y) & (col("month") == m) & (col("day") == d))

print(f"Writing only today's partitions for {DATE} to {output_path}")

df_today.write.mode("overwrite") \
    .partitionBy(*partition_cols) \
    .parquet(output_path)

df_1m_base.unpersist()
print("Job completed safely with IST-aligned partitions.")
