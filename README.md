# EX予約 / スマートEX 領収書ダウンロードツール

指定した月の領収書をすべて PDF で保存します。Playwright でブラウザを操作し、
ログイン後の会員メニュー「ご利用履歴・領収書の発行」から一覧へ進み、照会期間に
**対象月の初日〜末日**を選んで全件表示 → 1件ずつ 宛名入力 → 「印刷」で開く正式な
領収書を PDF 化します。**Web UI（フォーム）** と **CLI** の2通りで使えます。

**ログインは資格情報を保存しません。** 実行するとブラウザが開くので、会員ID・パスワードを
手入力してください。**会員メニューに到達すると自動検知**して続行します（CLIでは Enter でも可）。
ログイン後はセッションが `./.auth/state.json` に保存され、次回以降は自動でスキップされます。

> ⚠️ この処理は**お使いのPC上のブラウザ操作とデスクトップ保存**を伴うため、必ずローカルで
> 実行します。GitHub のサーバー（Pages/Actions）上では実行できません。GitHub はコードの
> 保管・共有用です。

## Web UI（フォームから実行）

年・月・宛名・サービスを選んで「実行する」を押すと、ローカルにブラウザが開きます。
ログインすると指定月の領収書をすべてデスクトップに保存し、進捗が画面に表示されます。
使い方は2通り:

### A. ローカルだけで使う（最も簡単）
```bash
python3 webapp.py
# → 自動で http://127.0.0.1:8765 が開く（開かなければ手動で開く）
```

### B. GitHub Pages の URL で画面を開く（ローカルヘルパー方式）
画面を `https://<ユーザー名>.github.io/ex-receipt-downloader/` で開けるようにする方式です。
**実行処理はこの場合もあなたのPCで動きます**（ページからローカルのヘルパーを呼び出す）。

1. リポジトリの **Settings → Pages → Source: Deploy from a branch → `main` / `/docs`** を保存
   （数分で `https://<ユーザー名>.github.io/ex-receipt-downloader/` が公開）。
2. ローカルヘルパーを起動（`http://127.0.0.1:8765` で待ち受け）:
   ```
   Finder で scripts/start_helper.command をダブルクリック（ウィンドウは開いたまま）
   ```
3. 上記 Pages の URL を **Chrome** で開く → 「✅ ローカルヘルパー稼働中」と出れば実行できます。
   （`http://localhost:8765` を直接開いても同じ画面が使えます）

> ヘルパーは `127.0.0.1` のみで待ち受け、許可オリジンは自分の `*.github.io` と `localhost`
> だけ（CORS/Private Network Access で制限）。**Chrome 推奨**（Safari はローカル接続を
> ブロックする場合あり）。

**ログイン時の自動起動にしたい場合**: `システム設定 → 一般 → ログイン項目` に
`scripts/start_helper.command` を追加してください（ログイン時にヘルパーが起動）。

> 補足: macOS のプライバシー保護(TCC)により、**バックグラウンド常駐(LaunchAgent)では
> OneDrive 等の保護フォルダ内のファイルを起動できません**。そのため上記のダブルクリック/
> ログイン項目方式（=あなたの権限で起動）を使います。完全な常時バックグラウンド化を望む
> 場合は、リポジトリを `~/ex-receipt-downloader` など保護対象外の場所に置いて運用してください。

## 仕組み（重要な前提）

- 一覧の照会期間（From/To の年月・日プルダウン）に **対象月の初日〜末日** を設定して
  「再検索」し、表示された領収書を全件取得します（当月指定時は末日を今日までにクランプ）。
- 各行の「領収書表示」→ 明細で宛名（上段）を入力 → 「印刷」を押すと**別ウィンドウに正式な
  領収書**が開きます。OSのネイティブ印刷ダイアログは自動操作できないため、その**別ウィンドウ
  （ダイアログが印刷する対象そのもの）を CDP `Page.printToPDF` で PDF 化**します（結果は同一。
  `window.print()` は固まり防止で無効化）。**1領収書=1PDF**、ファイル名は乗車日ベースで一意化し
  **デスクトップ**へ保存します（`OUTPUT_DIR` で変更可）。
- サイト制約: 予約完了日**当日は不可**、翌日〜**最大15ヶ月**、**23:30〜5:30はメンテで利用不可**。
  これらはツール側でも事前チェック／警告します。

## 構成

```
webapp.py               ローカルWeb UI / API（フォーム→実行→進捗、CORS対応）
docs/index.html         GitHub Pages 用の画面（ローカルヘルパーを呼び出す静的UI）
scripts/setup.*         初回セットアップ（.bat=Win / .command=mac / .sh=Linux）
scripts/start_helper.*  ヘルパー起動（.bat=Win / .command=mac / .sh=Linux）
main.py                 CLI（引数解釈・設定上書き・--check）
pipeline.py             決定論パイプライン（login→一覧→照会→逐次DL→集計）
config.py               設定とセレクタの集約（SELECTORS）／利用可否判定
browser_manager.py      単一ブラウザコンテキスト＋セッション(storage_state)／window.print無効化
datetools.py            日本語日付の抽出・解析（ファイル名用）
agents/login_agent.py   手入力ログイン（自動検知）／保存セッション再利用
agents/discovery_agent.py  会員メニュー→一覧 到達・照会(From/To)・領収書表示・戻る
agents/download_agent.py   宛名入力→印刷ポップアップ(正式な領収書)をPDF化
```

> 旧 `orchestrator.py`（LLM でツール順序を決める実装）は廃止しました。処理順は固定で
> 分岐がないため、LLM を挟まず単純で再現性のある手続きにしています（anthropic 依存も削除）。

## セットアップ（どのPCでも：Windows / macOS / Linux）

前提: **Python 3.9 以上**。Windows は https://www.python.org/downloads/ から入れる際に
「Add python.exe to PATH」にチェック。`git clone` するか、リポジトリを ZIP でダウンロードして展開します。

**かんたんセットアップ（ダブルクリック）**
- Windows: `scripts\setup.bat` をダブルクリック
- macOS: `scripts/setup.command` をダブルクリック（初回は右クリック→開く）
- Linux: `bash scripts/setup.sh`

これで依存パッケージと Playwright 用 Chromium（各OS向け、約150MB）が入ります。

**手動で行う場合**
```bash
# Windows:  py -3 -m pip install -r requirements.txt && py -3 -m playwright install chromium
# macOS  :  python3 -m pip install -r requirements.txt && python3 -m playwright install chromium
# Linux  :  python3 -m pip install -r requirements.txt && python3 -m playwright install --with-deps chromium
```

> 宛名の既定値などを変えたい場合のみ `.env`（`.env.example` をコピー）を作成。ID/PWの設定は不要です。
> Windows は `python` / `py`、macOS/Linux は `python3` を使います。

## 起動（Web UI）

- Windows: `scripts\start_helper.bat` をダブルクリック
- macOS: `scripts/start_helper.command` をダブルクリック
- Linux: `bash scripts/start_helper.sh`
- いずれも `http://localhost:8765` が開きます（GitHub Pages を有効化していれば公開URLからも可）。

## 使い方（CLI）

```bash
# 設定と照会期間・利用可否だけ確認（ブラウザを起動しない）
python3 main.py 2024/01 --check

# 通常実行：ブラウザが開く→ID/PW＋SMS認証を手入力→会員メニュー到達で自動継続
python3 main.py 2024/01

# 別指定
python3 main.py --year 2024 --month 1
python3 main.py 2024/01 --service expy --recipient "株式会社○○"
```

## ⚠️ 初回は必ず動作確認（セレクタ未検証）

このツールのサイト操作（照会欄・領収書ボタン等のセレクタ）は **実アカウントで未検証**です。
実DOMに合わせて `config.py` の `SELECTORS` を調整する前提で作っています。
初回は **--debug** を付けて実行し、各ステップを目視＆ファイル確認してください。

```bash
python3 main.py 2024/01 --debug
```

- 初回はブラウザが自動で開きます。会員ID・パスワードを手入力し、ログイン完了後に
  ターミナルで Enter を押してください。セッションは `./.auth/state.json` に保存されます。
- `output/debug_*.png` / `output/debug_*.html` が各ステップで保存されます。
  うまくいかない箇所に応じて `config.py` の `SELECTORS` を修正します。
- 保存済みセッションがあるときも画面で確認したい場合は `--no-headless` を付けます。

3. ファイル名の日付が行内の別日付になる場合は `TRAVEL_DATE_INDEX`
   （既定0=行内の最初の日付）を調整。`--debug` 実行時に各行で検出した日付トークンが
   ログ出力されます。

### 調整しやすいポイント（config.py `SELECTORS`）

| キー | 用途 |
|---|---|
| `login_success_keywords` | ログイン済み（セッション有効）判定に使う文言 |
| `menu_receipt_link` | 会員メニューから領収書一覧へのリンク文言 |
| `proceed_to_list` | ガイド/手順画面で一覧へ進むボタン文言 |
| `filter_start_keywords` / `filter_end_keywords` | 照会期間の日付入力欄 |
| `filter_submit_texts` | 照会ボタン文言 |
| `receipt_button` | 一覧各行の「領収書表示」ボタン |
| `pager_next` | ページ送り「次へ」 |
| `atena_input` | 宛名入力欄 |

## 出力ファイル名

`領収書_<日付YYYYMMDD>_<連番>_<金額>円.pdf`（日付/金額が取れない場合は連番のみ）。
同名があれば `_2`, `_3`… を付けて一意にします。既定の保存先はデスクトップ。

## 注意・免責

- `.env` と `.auth/`（ログインセッション）は秘匿情報です。共有・コミットしないでください
  （同梱の `.gitignore` で除外済み）。
- 本ツールは**自分自身のアカウント**の領収書取得を自動化する目的のものです。
  サイトの利用規約を尊重し、過度なアクセスは避けてください。
- 非公式ツールです。JR東海・スマートEX・エクスプレス予約とは一切関係ありません。
  サイト仕様変更で動作しなくなる場合があります（セレクタは `config.py` に集約）。
- 本ソフトウェアは無保証です。利用は自己責任でお願いします。

## ライセンス

[MIT License](LICENSE)
