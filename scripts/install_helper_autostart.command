#!/bin/bash
# ローカル常駐ヘルパー（webapp.py）をログイン時に自動起動する設定。
# このファイルを Finder でダブルクリックすると実行できます。
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="$(command -v python3 || echo /usr/bin/python3)"
LABEL="com.horiken1977.exreceipt"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$PROJECT_DIR/output"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$PROJECT_DIR/webapp.py</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>EXRECEIPT_NO_OPEN</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$PROJECT_DIR/output/helper.log</string>
  <key>StandardErrorPath</key><string>$PROJECT_DIR/output/helper.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "✅ 自動起動を設定しました（ログイン時に常駐ヘルパーが起動します）。"
echo "   ヘルパー: http://127.0.0.1:8765"
echo "   画面(GitHub Pages): https://horiken1977.github.io/ex-receipt-downloader/"
echo "   ログ: $PROJECT_DIR/output/helper.log"
echo ""
echo "数秒後に上記URLを開いて「✅ ローカルヘルパー稼働中」と出れば成功です。"
