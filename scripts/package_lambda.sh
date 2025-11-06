#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for fn in oauth_gateway ingest_history; do
  pushd "$ROOT/lambdas/$fn" >/dev/null
  rm -f "$fn".zip
  pip install -r requirements.txt -t . >/dev/null
  zip -qr "$fn".zip . -x "*.pyc" "__pycache__/*" ".venv/*"
  mv "$fn".zip "$ROOT/infra/terraform/"
  git restore . 2>/dev/null || true
  popd >/dev/null
done
echo "Zips created under infra/terraform/"
