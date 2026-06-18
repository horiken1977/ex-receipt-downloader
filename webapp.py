#!/usr/bin/env python3
"""
EX予約 領収書ダウンロード — ローカルWeb UI。

ブラウザのフォーム（年・月・宛名・サービス）から実行を起動し、main.py と同じ
パイプラインを動かす。実行するとローカルにChromiumが開くので手動ログイン、
以後は対象月の自動選択→宛名入力→印刷→PDF保存（デスクトップ）まで自動で進む。

注意: この処理はローカルのブラウザ操作とデスクトップ保存を伴うため、必ず
お使いのPC上で動かす（GitHubのサーバー等では実行できない）。

使い方:
    python3 webapp.py
    → ブラウザで http://127.0.0.1:5000 を開く
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import webbrowser

from flask import Flask, jsonify, request

import config

app = Flask(__name__)

# 実行状態（単一実行のみ許可）
_state = {"running": False, "log": [], "result": None, "params": None}
_lock = threading.Lock()


# --- CORS / Private Network Access -----------------------------------------
# GitHub Pages(https) の画面からローカルヘルパー(http://127.0.0.1) を呼べるようにする。
# 許可オリジンは github.io と localhost のみ（無関係なサイトからの実行を防ぐ）。
# macOS の AirPlay レシーバーがポート5000を占有するため 8765 を使う。
PORT = int(os.getenv("EXRECEIPT_PORT", "8765"))


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    return (origin.endswith(".github.io")
            or origin in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"))


@app.before_request
def _handle_preflight():
    from flask import request as _rq
    if _rq.method == "OPTIONS":
        return ("", 204)


@app.after_request
def _add_cors(resp):
    from flask import request as _rq
    origin = _rq.headers.get("Origin", "")
    if _origin_allowed(origin):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


class _LogWriter:
    """print 出力をWeb表示用バッファへ流す。"""

    def __init__(self, original):
        self._original = original

    def write(self, s):
        if self._original:
            try:
                self._original.write(s)
            except Exception:
                pass
        if s and s.strip():
            with _lock:
                _state["log"].append(s.rstrip("\n"))

    def flush(self):
        if self._original:
            try:
                self._original.flush()
            except Exception:
                pass


def _run_pipeline(year: int, month: int, recipient: str, service: str, debug: bool):
    from pipeline import Pipeline  # playwright 依存をここで読む

    with _lock:
        _state.update(running=True, log=[], result=None,
                      params={"year": year, "month": month, "recipient": recipient, "service": service})

    config.SERVICE_TYPE = service
    config.RECIPIENT_NAME = recipient
    config.HEADLESS = False  # ログインのため必ず画面表示
    config.DEBUG = debug

    old_stdout = sys.stdout
    sys.stdout = _LogWriter(old_stdout)
    try:
        avail = config.check_month_available(year, month)
        if not avail.ok:
            print(f"[Web] 中止: {avail.reason}")
        else:
            result = asyncio.run(Pipeline(year=year, month=month).run())
            with _lock:
                _state["result"] = result
    except Exception as e:
        print(f"[Web] エラー: {e}")
    finally:
        sys.stdout = old_stdout
        with _lock:
            _state["running"] = False


_DOCS_INDEX = config.BASE_DIR / "docs" / "index.html"


@app.route("/")
def index():
    # GitHub Pages と同じ画面（docs/index.html）をローカルでも配信する。
    try:
        return _DOCS_INDEX.read_text(encoding="utf-8")
    except Exception:
        return "docs/index.html が見つかりません。", 500


@app.route("/config")
def get_config():
    return jsonify(recipient=config.RECIPIENT_NAME, service=config.SERVICE_TYPE)


@app.route("/run", methods=["POST", "OPTIONS"])
def run():
    if _state["running"]:
        return jsonify(started=False, running=True)
    try:
        year = int(request.form["year"])
        month = int(request.form["month"])
    except (KeyError, ValueError):
        return jsonify(error="年と月を指定してください。"), 400
    recipient = (request.form.get("recipient") or config.RECIPIENT_NAME).strip()
    service = request.form.get("service", "smart-ex")
    debug = request.form.get("debug") == "on"

    t = threading.Thread(target=_run_pipeline, args=(year, month, recipient, service, debug), daemon=True)
    t.start()
    return jsonify(started=True)


@app.route("/status", methods=["GET", "OPTIONS"])
def status():
    with _lock:
        return jsonify(running=_state["running"], log=_state["log"],
                       result=_state["result"], params=_state["params"])


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 56)
    print("EX予約 領収書ダウンロード Web UI")
    print(f"  ブラウザで {url} を開いてください")
    print("  停止: Ctrl+C")
    print("=" * 56)
    if os.getenv("EXRECEIPT_NO_OPEN") != "1":
        try:
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        except Exception:
            pass
    try:
        app.run(host="127.0.0.1", port=PORT, debug=False)
    except OSError as e:
        print(f"\n[起動失敗] ポート {PORT} は既に使用中の可能性があります: {e}")
        if sys.platform == "win32":
            print(f'  解放: コマンドプロンプトで  netstat -ano | findstr :{PORT}  → taskkill /F /PID <番号>')
        else:
            print(f"  解放: ターミナルで  lsof -ti:{PORT} | xargs kill")
        print(f"  もしくは別ポートで起動:  EXRECEIPT_PORT=8780 で再実行（画面側の接続先も変わる点に注意）")
        sys.exit(1)
