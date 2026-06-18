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
import datetime
import os
import sys
import threading
import webbrowser

from flask import Flask, jsonify, redirect, render_template_string, request

import config

app = Flask(__name__)

# 実行状態（単一実行のみ許可）
_state = {"running": False, "log": [], "result": None, "params": None}
_lock = threading.Lock()


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


@app.route("/")
def index():
    today = datetime.date.today()
    years = [today.year, today.year - 1]
    return render_template_string(
        INDEX_HTML,
        years=years,
        cur_year=today.year,
        cur_month=today.month,
        recipient=config.RECIPIENT_NAME,
        service=config.SERVICE_TYPE,
        running=_state["running"],
    )


@app.route("/run", methods=["POST"])
def run():
    if _state["running"]:
        return redirect("/progress")
    try:
        year = int(request.form["year"])
        month = int(request.form["month"])
    except (KeyError, ValueError):
        return redirect("/")
    recipient = (request.form.get("recipient") or config.RECIPIENT_NAME).strip()
    service = request.form.get("service", "smart-ex")
    debug = request.form.get("debug") == "on"

    t = threading.Thread(target=_run_pipeline, args=(year, month, recipient, service, debug), daemon=True)
    t.start()
    return redirect("/progress")


@app.route("/progress")
def progress():
    return render_template_string(PROGRESS_HTML)


@app.route("/status")
def status():
    with _lock:
        return jsonify(running=_state["running"], log=_state["log"],
                       result=_state["result"], params=_state["params"])


INDEX_HTML = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EX予約 領収書ダウンロード</title>
<style>
 body{font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;max-width:620px;margin:40px auto;padding:0 16px;color:#222}
 h1{font-size:20px} .card{border:1px solid #ddd;border-radius:10px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.06)}
 label{display:block;margin:14px 0 4px;font-weight:600;font-size:14px}
 select,input[type=text]{width:100%;padding:10px;border:1px solid #ccc;border-radius:8px;font-size:15px;box-sizing:border-box}
 .row{display:flex;gap:12px}.row>div{flex:1}
 button{margin-top:20px;width:100%;padding:12px;background:#0b5fff;color:#fff;border:0;border-radius:8px;font-size:16px;cursor:pointer}
 .note{background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:12px;font-size:13px;line-height:1.6;margin-top:16px}
 .ck{display:flex;align-items:center;gap:8px;margin-top:14px;font-size:14px}
 .ck input{width:auto}
</style></head><body>
<h1>🚄 EX予約 領収書ダウンロード</h1>
<div class="card">
 <form method="post" action="/run">
  <div class="row">
   <div><label>年</label><select name="year">
     {% for y in years %}<option value="{{y}}" {{'selected' if y==cur_year}}>{{y}}年</option>{% endfor %}
   </select></div>
   <div><label>月</label><select name="month">
     {% for m in range(1,13) %}<option value="{{m}}" {{'selected' if m==cur_month}}>{{m}}月</option>{% endfor %}
   </select></div>
  </div>
  <label>宛名</label>
  <input type="text" name="recipient" value="{{recipient}}" placeholder="宛名（20文字まで）">
  <label>サービス</label>
  <select name="service">
   <option value="smart-ex" {{'selected' if service=='smart-ex'}}>スマートEX</option>
   <option value="expy" {{'selected' if service=='expy'}}>エクスプレス予約</option>
  </select>
  <div class="ck"><input type="checkbox" name="debug" id="debug"><label for="debug" style="margin:0;font-weight:400">デバッグ（各ステップのスクショ/HTMLを保存）</label></div>
  <button type="submit">実行する</button>
 </form>
 <div class="note">
  実行すると<b>このPC上にChromiumが開きます</b>。会員ID・パスワードを手入力してログインしてください。
  会員メニューに到達すると自動検知し、指定月の領収書をすべて<b>デスクトップ</b>にPDF保存します。<br>
  ※ ログイン情報は保存しません。23:30〜5:30はサイトメンテナンスで利用できません。
 </div>
</div>
</body></html>
"""

PROGRESS_HTML = """
<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>実行中… EX予約 領収書ダウンロード</title>
<style>
 body{font-family:-apple-system,"Hiragino Kaku Gothic ProN",sans-serif;max-width:760px;margin:30px auto;padding:0 16px;color:#222}
 h1{font-size:18px} #log{background:#0b1021;color:#d6e2ff;border-radius:10px;padding:14px;height:50vh;overflow:auto;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;white-space:pre-wrap}
 .badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:13px}
 .run{background:#fff3cd;color:#7a5c00}.done{background:#d4edda;color:#155724}
 .files{margin-top:14px}.files li{font-family:ui-monospace,monospace;font-size:12.5px}
 a{color:#0b5fff}
</style></head><body>
<h1>EX予約 領収書ダウンロード <span id="badge" class="badge run">実行中…</span></h1>
<div id="log">起動中…</div>
<div id="summary"></div>
<p style="margin-top:18px"><a href="/">← フォームに戻る</a></p>
<script>
async function tick(){
  try{
    const r = await fetch('/status'); const s = await r.json();
    const log = document.getElementById('log');
    log.textContent = (s.log||[]).join('\\n'); log.scrollTop = log.scrollHeight;
    const badge = document.getElementById('badge');
    if(!s.running){
      badge.textContent = '完了'; badge.className='badge done';
      if(s.result){
        const f = s.result.downloaded_files||[]; const fail=(s.result.failed||[]).length;
        let h = '<div class="files"><b>ダウンロード成功: '+f.length+'件</b>'+(fail?'（失敗 '+fail+'件）':'')+'<ul>';
        f.forEach(p=>{h+='<li>'+p+'</li>';}); h+='</ul></div>';
        document.getElementById('summary').innerHTML = h;
      }
      return; // 停止
    }
  }catch(e){}
  setTimeout(tick, 1500);
}
tick();
</script>
</body></html>
"""


if __name__ == "__main__":
    url = "http://127.0.0.1:5000"
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
    app.run(host="127.0.0.1", port=5000, debug=False)
