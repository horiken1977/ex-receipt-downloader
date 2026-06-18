@echo off
chcp 65001 >nul
rem EX予約 領収書ダウンロード — 初回セットアップ（Windows）
rem このファイルをダブルクリックすると、必要なものをインストールします。
cd /d "%~dp0.."

echo ============================================================
echo  EX予約 領収書ダウンロード セットアップ (Windows)
echo ============================================================

rem python ランチャ(py)があれば優先、無ければ python
where py >nul 2>&1 && (set "PY=py -3") || (set "PY=python")

echo [1/2] Python パッケージをインストール...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto err

echo [2/2] Playwright の Chromium をインストール...
%PY% -m playwright install chromium
if errorlevel 1 goto err

echo.
echo 完了しました。scripts\start_helper.bat をダブルクリックで起動できます。
pause
exit /b 0

:err
echo.
echo エラーが発生しました。Python 3.9 以上がインストールされているか確認してください。
echo   https://www.python.org/downloads/ （インストール時に "Add python.exe to PATH" にチェック）
pause
exit /b 1
