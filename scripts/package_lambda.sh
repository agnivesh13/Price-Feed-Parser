#!/usr/bin/env bash

# Set the root directory and exit immediately if any command fails
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Check if the 'callback_handler' directory exists and package it
TARGET_DIR="src/lambda/callback_handler"
if [ ! -d "$TARGET_DIR" ]; then
  echo "Directory $TARGET_DIR does not exist. Aborting."
  exit 1
fi
pushd "$TARGET_DIR"
rm -f callback_handler.zip
pip install -r requirements.txt -t . >/dev/null
zip -qr callback_handler.zip . -x "*.pyc" "__pycache__/*" ".venv/*"
mv callback_handler.zip "$ROOT/infra/terraform/"
git restore . 2>/dev/null || true
popd >/dev/null

# Check if the 'ingest_lambda' directory exists and package it
TARGET_DIR="src/lambda/ingest_lambda"
if [ ! -d "$TARGET_DIR" ]; then
  echo "Directory $TARGET_DIR does not exist. Aborting."
  exit 1
fi
pushd "$TARGET_DIR"
rm -f ingest_lambda.zip
pip install -r requirements.txt -t . >/dev/null
zip -qr ingest_lambda.zip . -x "*.pyc" "__pycache__/*" ".venv/*"
mv ingest_lambda.zip "$ROOT/infra/terraform/"
git restore . 2>/dev/null || true
popd >/dev/null

# If you have any other Lambda directories, repeat the same process as above

echo "Zips created under infra/terraform/"
