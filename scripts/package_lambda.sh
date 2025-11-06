#!/usr/bin/env bash
TARGET_DIR="lambdas/oauth_gateway"
if [ ! -d "$TARGET_DIR" ]; then
  echo "Directory $TARGET_DIR does not exist. Aborting."
  exit 1
fi
pushd "$TARGET_DIR"
# … rest of script …

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
