#!/bin/bash
# EX予約 領収書ダウンロード — 初回セットアップ（Linux）
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1

echo "=== EX receipt downloader setup (Linux) ==="
PY="$(command -v python3 || echo python3)"

echo "[1/2] pip install ..."
"$PY" -m pip install -r requirements.txt || { echo "pip install failed"; exit 1; }

echo "[2/2] playwright install chromium ..."
"$PY" -m playwright install --with-deps chromium || "$PY" -m playwright install chromium || { echo "playwright install failed"; exit 1; }

echo "Done. Run scripts/start_helper.sh to launch."
