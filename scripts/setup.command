#!/bin/bash
# EX予約 領収書ダウンロード — 初回セットアップ（macOS）
# Finder でこのファイルをダブルクリックすると、必要なものをインストールします。
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1

echo "============================================================"
echo " EX予約 領収書ダウンロード セットアップ (macOS)"
echo "============================================================"

PY="$(command -v python3 || echo python3)"

echo "[1/2] Python パッケージをインストール..."
"$PY" -m pip install -r requirements.txt || { echo "pip install に失敗しました"; exit 1; }

echo "[2/2] Playwright の Chromium をインストール..."
"$PY" -m playwright install chromium || { echo "playwright install に失敗しました"; exit 1; }

echo ""
echo "完了しました。scripts/start_helper.command をダブルクリックで起動できます。"
