#!/bin/bash
# EX予約 領収書ダウンロード — ローカルヘルパー起動（Linux）
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1

echo "EX receipt helper: http://localhost:8765  (Ctrl+C to stop)"

# ポート8765 を使っている既存プロセスがあれば停止（二重起動防止）
EXIST="$(lsof -ti:8765 2>/dev/null)"
if [ -n "$EXIST" ]; then
  echo "stopping existing helper (PID: $EXIST)..."
  kill $EXIST 2>/dev/null
  sleep 1
fi

exec python3 webapp.py
