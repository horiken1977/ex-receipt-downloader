@echo off
chcp 65001 >nul
rem EX予約 領収書ダウンロード — ローカルヘルパー起動（Windows）
rem このファイルをダブルクリックすると起動します。
cd /d "%~dp0.."

echo ============================================================
echo  EX予約 領収書ダウンロード ヘルパー
echo    画面(ローカル):     http://localhost:8765
echo    画面(GitHub Pages): https://horiken1977.github.io/ex-receipt-downloader/
echo    終了: このウィンドウを閉じる
echo ============================================================

rem ポート8765 を使っている既存プロセスがあれば停止（二重起動防止・best-effort）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":8765"') do taskkill /F /PID %%a >nul 2>&1

where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")
%PY% webapp.py
pause
