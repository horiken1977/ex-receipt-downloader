#!/bin/bash
# EX予約 領収書ダウンロード — ローカル常駐ヘルパーを起動する。
# Finder でこのファイルをダブルクリックすると起動できます。
# （この方式は端末経由なので、OneDrive等の保護フォルダ配下でも動作します）
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1

echo "============================================================"
echo " EX予約 領収書ダウンロード ヘルパー"
echo "   画面(ローカル):  http://localhost:8765"
echo "   画面(GitHub Pages): https://horiken1977.github.io/ex-receipt-downloader/"
echo "   終了: このウィンドウで Ctrl+C、またはウィンドウを閉じる"
echo "============================================================"

exec python3 webapp.py
