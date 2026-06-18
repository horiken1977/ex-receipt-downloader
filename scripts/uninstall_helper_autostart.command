#!/bin/bash
# ローカル常駐ヘルパーの自動起動を解除する。Finder でダブルクリックして実行。
LABEL="com.horiken1977.exreceipt"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "✅ 自動起動を解除しました（常駐ヘルパーは次回ログインから起動しません）。"
echo "   今すぐ止める場合は、起動中の python3 webapp.py を終了してください。"
